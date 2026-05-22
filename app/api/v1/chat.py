from fastapi import APIRouter, Depends
from starlette.concurrency import run_in_threadpool

from app.models import UnifiedAIChatRequest
from app.dependencies import get_router_service
from app.services.router import RouterService
from app.core.prompts import get_task_system_prompt

router = APIRouter()


@router.post("/unified")
async def unified_chat(
    req: UnifiedAIChatRequest,
    router_svc: RouterService = Depends(get_router_service),
):
    """
    Voice coaching scoring endpoint.
    Sends transcribed speech + prompt to LLM for evaluation.
    """
    messages = []

    system_prompt = req.system_prompt or get_task_system_prompt(req.task)
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})

    # Append conversation history from request
    if req.history:
        for msg in req.history:
            messages.append({"role": msg.role, "content": msg.content})

    messages.append({"role": "user", "content": req.query})

    # Call router with task-based failover
    response, meta = await router_svc.chat_with_failover(
        messages=messages,
        user_id=req.user_id,
        model_override=req.model_override,
        task=req.task
    )

    answer = response.choices[0].message.content
    usage = response.usage

    return {
        "answer": answer,
        "metadata": meta,
        "usage": usage.model_dump() if usage else None
    }
