use axum::{
    extract::State,
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    Json,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use jsonwebtoken::{decode, DecodingKey, Validation, Algorithm};
use redis::AsyncCommands;
use crate::main::AppState;
use std::time::Duration;
use tokio::time::Instant;

#[derive(Debug, Serialize, Deserialize)]
pub struct Claims {
    pub sub: String,
    pub role: String,
    pub exp: usize,
}

#[derive(Serialize)]
pub struct JsonRpcError {
    code: i32,
    message: String,
}

#[derive(Serialize)]
pub struct JsonRpcResponse {
    jsonrpc: String,
    id: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    result: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<JsonRpcError>,
}

pub async fn handle_mcp_request(
    headers: HeaderMap,
    State(state): State<Arc<AppState>>,
    Json(mut payload): Json<serde_json::Value>,
) -> impl IntoResponse {
    // 1. Token Extraction & ACL
    let auth_header = headers.get("Authorization")
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");

    let role = if auth_header.starts_with("Bearer ") {
        let token = &auth_header[7..];
        let mut validation = Validation::new(Algorithm::HS256);
        validation.insecure_disable_signature_check();
        match decode::<Claims>(token, &DecodingKey::from_secret("secret".as_ref()), &validation) {
            Ok(token_data) => token_data.claims.role,
            Err(_) => "default".to_string(),
        }
    } else {
        "default".to_string()
    };

    // 2. Rate Limiting Check
    let redis_url = std::env::var("REDIS_URL").unwrap_or_else(|_| "redis://127.0.0.1:6379".to_string());
    if let Ok(client) = redis::Client::open(redis_url) {
        if let Ok(mut con) = client.get_tokio_connection().await {
            let key = format!("rate_limit:{}", role);
            let count: i32 = con.incr(&key, 1).await.unwrap_or(0);
            let _: () = con.expire(&key, 60).await.unwrap_or(());
            let limit = if role == "admin" { 1000 } else { 60 };
            
            if count > limit {
                log::warn!("Rate limit exceeded for role: {}", role);
                return (
                    StatusCode::TOO_MANY_REQUESTS,
                    Json(JsonRpcResponse {
                        jsonrpc: "2.0".to_string(),
                        id: payload.get("id").cloned(),
                        result: None,
                        error: Some(JsonRpcError { code: -32000, message: "Rate limit exceeded".to_string() }),
                    }),
                );
            }
        }
    }

    // 3. Inject Context into Payload (CABP)
    if let Some(params) = payload.get_mut("params").and_then(|p| p.as_object_mut()) {
        params.insert("user_identity".to_string(), serde_json::json!({ "role": role }));
    }

    // 4. ATBA Orchestration Check
    // If the request is specifically a tool chain, we handle it in the gateway.
    let is_tool_call = payload.get("method").and_then(|m| m.as_str()) == Some("tools/call");
    let tool_name = payload.get("params").and_then(|p| p.get("name")).and_then(|n| n.as_str()).unwrap_or("");

    if is_tool_call && tool_name == "orchestrate_chain" {
        return handle_atba_chain(state, payload).await;
    }

    // Standard single tool call: wrap with a basic timeout if needed, or just forward
    match state.proxy.send_request(payload).await {
        Ok(response) => (StatusCode::OK, Json(serde_json::from_value(response).unwrap())),
        Err(e) => {
            log::error!("Proxy error: {}", e);
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(JsonRpcResponse {
                    jsonrpc: "2.0".to_string(),
                    id: None,
                    result: None,
                    error: Some(JsonRpcError { code: -32603, message: "Internal proxy error".to_string() }),
                }),
            )
        }
    }
}

async fn handle_atba_chain(state: Arc<AppState>, payload: serde_json::Value) -> (StatusCode, Json<JsonRpcResponse>) {
    let id = payload.get("id").cloned();
    let args = payload.get("params").and_then(|p| p.get("arguments"));
    let chain = args.and_then(|a| a.get("chain")).and_then(|c| c.as_array());

    if chain.is_none() {
        return (StatusCode::BAD_REQUEST, Json(JsonRpcResponse {
            jsonrpc: "2.0".to_string(),
            id,
            result: None,
            error: Some(JsonRpcError { code: -32602, message: "Missing chain argument".to_string() }),
        }));
    }

    let mut tool_names: Vec<String> = Vec::new();
    let mut tool_requests: Vec<serde_json::Value> = Vec::new();

    for item in chain.unwrap() {
        if let Some(name) = item.get("name").and_then(|n| n.as_str()) {
            tool_names.push(name.to_string());
            tool_requests.push(item.clone());
        }
    }

    let mut budgets = state.atba.allocate_initial_budget(&tool_names);
    let mut results = Vec::new();

    for (i, req) in tool_requests.into_iter().enumerate() {
        let name = tool_names[i].clone();
        let budget_ms = budgets.get(&name).copied().unwrap_or(5000);
        let remaining_tools = &tool_names[i + 1..];

        // Format an individual tool call payload
        let mut individual_payload = serde_json::json!({
            "jsonrpc": "2.0",
            "id": i,
            "method": "tools/call",
            "params": req
        });

        let start_time = Instant::now();
        
        let timeout_duration = Duration::from_millis(budget_ms);
        let result = tokio::time::timeout(timeout_duration, state.proxy.send_request(individual_payload)).await;

        let elapsed = start_time.elapsed().as_millis() as u64;
        
        match result {
            Ok(Ok(response)) => {
                // Success: cascade surplus budget
                state.atba.complete_tool_and_cascade(&name, elapsed, &mut budgets, remaining_tools);
                results.push(response);
            }
            Ok(Err(e)) => {
                // Proxy error
                return (StatusCode::INTERNAL_SERVER_ERROR, Json(JsonRpcResponse {
                    jsonrpc: "2.0".to_string(),
                    id,
                    result: None,
                    error: Some(JsonRpcError { code: -32603, message: format!("Tool {} failed: {}", name, e) }),
                }));
            }
            Err(_) => {
                // Timeout!
                return (StatusCode::GATEWAY_TIMEOUT, Json(JsonRpcResponse {
                    jsonrpc: "2.0".to_string(),
                    id,
                    result: None,
                    error: Some(JsonRpcError { code: -32001, message: format!("SERF Timeout: Tool {} exceeded budget {}ms", name, budget_ms) }),
                }));
            }
        }
    }

    (StatusCode::OK, Json(JsonRpcResponse {
        jsonrpc: "2.0".to_string(),
        id,
        result: Some(serde_json::json!({ "chain_results": results })),
        error: None,
    }))
}
