"""
Claude client wrapper for structured insight generation.

Uses tool use to enforce the output schema — the model is forced to call
`emit_insight` exactly once and populate every required field. No JSON-fence
parsing, no repair libraries.

Extended thinking is enabled for analytical depth.
Prompt caching is applied to the static system block.
"""

from __future__ import annotations

import time
from typing import Any

import anthropic

from app.config import Settings
from app.logging_config import get_logger
from app.schemas.insights import InsightToolInput

logger = get_logger(__name__)

_PROMPT_VERSION = "insights_v1"


def _build_tool(schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": "emit_insight",
        "description": (
            "Emit a structured insight with narrative, optional hypothesis, "
            "confidence score, and evidence chain."
        ),
        "input_schema": schema,
    }


async def call_llm(
    system_prompt: str,
    user_prompt: str,
    settings: Settings,
    retry_context: str | None = None,
) -> tuple[InsightToolInput, dict[str, Any]]:
    """
    Call Claude and return (parsed InsightToolInput, usage_dict).
    Raises ValueError if no valid tool call is found.
    """
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    tool = _build_tool(InsightToolInput.model_json_schema())

    # Prompt caching requires system to be a list of typed content blocks, not a plain string;
    # cache_control on the block tells the API to cache this text across repeated calls.
    system_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]

    user_content = user_prompt
    if retry_context:
        user_content += f"\n\n<grounding_failure>\n{retry_context}\n</grounding_failure>"

    call_kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "max_tokens": settings.llm_max_tokens,
        "tools": [tool],
        "tool_choice": {"type": "tool", "name": "emit_insight"},
        "system": system_content,
        "messages": [{"role": "user", "content": user_content}],
    }

    if settings.llm_enable_thinking:
        # budget_tokens must be strictly less than max_tokens or the API returns a validation error.
        call_kwargs["thinking"] = {
            "type": "enabled",
            "budget_tokens": settings.llm_thinking_budget,
        }

    t0 = time.monotonic()
    response = await client.messages.create(**call_kwargs)
    latency_ms = round((time.monotonic() - t0) * 1000)

    usage = response.usage
    thinking_tokens = getattr(usage, "thinking_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    cache_created = getattr(usage, "cache_creation_input_tokens", 0) or 0

    usage_dict = {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "thinking_tokens": thinking_tokens,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_created,
        "latency_ms": latency_ms,
    }

    # Extract the tool call block
    for block in response.content:
        if hasattr(block, "type") and block.type == "tool_use" and block.name == "emit_insight":
            parsed = InsightToolInput.model_validate(block.input)
            logger.info(
                "llm call complete",
                model=settings.llm_model,
                prompt_version=_PROMPT_VERSION,
                retry=retry_context is not None,
                **usage_dict,
            )
            return parsed, usage_dict

    raise ValueError("LLM response contained no emit_insight tool call")
