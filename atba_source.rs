use std::collections::{HashMap, VecDeque};
use std::sync::RwLock;

pub struct AtbaManager {
    total_budget_ms: u64,
    reserve_ratio: f64,
    window_size: usize,
    history: RwLock<HashMap<String, VecDeque<u64>>>,
}

impl AtbaManager {
    pub fn new(total_budget_ms: u64, reserve_ratio: f64, window_size: usize) -> Self {
        let mut initial_history = HashMap::new();
        
        // Seed history for standard tools
        let mut weather_hist = VecDeque::new();
        for val in [1000, 1200, 950, 1500, 1100] { weather_hist.push_back(val); }
        initial_history.insert("get_weather".to_string(), weather_hist);

        let mut db_hist = VecDeque::new();
        for val in [3000, 3100, 2800, 4000, 3200] { db_hist.push_back(val); }
        initial_history.insert("query_database".to_string(), db_hist);

        Self {
            total_budget_ms,
            reserve_ratio,
            window_size,
            history: RwLock::new(initial_history),
        }
    }

    pub fn record_latency(&self, tool_name: &str, latency_ms: u64) {
        let mut history = self.history.write().unwrap();
        let hist = history.entry(tool_name.to_string()).or_insert_with(VecDeque::new);
        hist.push_back(latency_ms);
        if hist.len() > self.window_size {
            hist.pop_front();
        }
    }

    pub fn calculate_p99(&self, tool_name: &str) -> u64 {
        let history = self.history.read().unwrap();
        if let Some(hist) = history.get(tool_name) {
            if hist.is_empty() {
                return 5000;
            }
            let mut sorted: Vec<u64> = hist.iter().copied().collect();
            sorted.sort_unstable();
            let idx = (0.99 * sorted.len() as f64).ceil() as usize;
            let safe_idx = idx.saturating_sub(1);
            return sorted[safe_idx];
        }
        5000 // Default P99 fallback
    }

    pub fn allocate_initial_budget(&self, tool_chain: &[String]) -> HashMap<String, u64> {
        let b_avail = (self.total_budget_ms as f64 * (1.0 - self.reserve_ratio)) as u64;
        let mut total_p99 = 0;
        let mut p99_values = HashMap::new();

        for tool in tool_chain {
            let p99 = self.calculate_p99(tool);
            p99_values.insert(tool.clone(), p99);
            total_p99 += p99;
        }

        let mut allocations = HashMap::new();
        if total_p99 == 0 { total_p99 = 1; }

        for tool in tool_chain {
            let p99 = p99_values.get(tool).unwrap();
            let alloc = (*p99 as f64 / total_p99 as f64) * b_avail as f64;
            allocations.insert(tool.clone(), alloc as u64);
        }

        allocations
    }

    pub fn complete_tool_and_cascade(
        &self,
        tool_name: &str,
        actual_time_ms: u64,
        current_budgets: &mut HashMap<String, u64>,
        remaining_tools: &[String],
    ) -> i64 {
        self.record_latency(tool_name, actual_time_ms);
        
        let allocated = current_budgets.get(tool_name).copied().unwrap_or(0);
        let surplus = allocated as i64 - actual_time_ms as i64;

        if surplus > 0 && !remaining_tools.is_empty() {
            let share = surplus as f64 / remaining_tools.len() as f64;
            for t in remaining_tools {
                if let Some(budget) = current_budgets.get_mut(t) {
                    *budget = (*budget as f64 + share) as u64;
                }
            }
        }

        surplus
    }
}
