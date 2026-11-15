"""AI node executors: AI Generate (``ai.generate``) and the AI Agent (``ai.agent``).

Both run real inference through the provider layer (``app.ai``). Nothing here is mocked: tests replace
only the provider client via ``app.ai.providers.set_chat_model_factory``.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel

from app.ai.agent import AgentRun
from app.ai.router import ModelRouter
from app.ai.structured import generate_structured, generate_text
from app.core.errors import ErrorCategory, NodeExecutionError
from app.engine.contracts import ExecutionContext, NodeExecutionResult, NodeExecutor
from app.executors import register
from app.registry.configs import AgentConfig, AIGenerateConfig


def _attach(exc: NodeExecutionError, **details: Any) -> NodeExecutionError:
    exc.error.details.update({k: v for k, v in details.items() if v is not None})
    return exc


def _finish_reason(message: Any) -> Any:
    meta = getattr(message, "response_metadata", None) or {}
    return meta.get("finish_reason") or meta.get("stop_reason") or meta.get("status")


@register
class AIGenerateExecutor(NodeExecutor):
    operation_id = "ai.generate"
    config_model = AIGenerateConfig

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, AIGenerateConfig)
        router = ModelRouter(ctx, config.model, None, operation=self.operation_id, max_retries=config.max_retries)
        trace: List[Dict[str, Any]] = []
        try:
            await router.prepare()
            system = config.system_prompt.strip()
            if config.output_format == "json":
                system = (system + "\n\n" if system else "") + "Respond only with a JSON object that matches the " \
                                                               "required output schema."
            prompt = config.prompt.strip()
            if config.inputs:
                prompt += "\n\nInputs (JSON):\n" + json.dumps(config.inputs, default=str, indent=2)
            if len(system) + len(prompt) > config.max_input_chars:
                raise NodeExecutionError(ErrorCategory.USAGE_LIMIT,
                                         f"The prompt is {len(system) + len(prompt)} characters, above the limit of "
                                         f"{config.max_input_chars}.", field="max_input_chars")
            messages: List[BaseMessage] = ([SystemMessage(content=system)] if system else []) + \
                [HumanMessage(content=prompt)]
            finish_reason = None
            if config.output_format == "json":
                assert config.output_schema is not None
                result: Any = await generate_structured(router, messages, config.output_schema,
                                                        config.max_repair_attempts, trace=trace)
            else:
                result, message = await generate_text(router, messages)
                finish_reason = _finish_reason(message)
        except NodeExecutionError as exc:
            raise _attach(exc, ai=router.summary() if router._slots else None, model_calls=router.attempts,
                          trace=trace or None) from None
        summary = router.summary()
        ctx.logger.info(f"Generated with {summary['provider']}/{summary['model']}",
                        {"usage": summary["usage"], "credential_source": summary["credential_source"]})
        return NodeExecutionResult(
            output={"result": result, "provider": summary["provider"], "model": summary["model"],
                    "usage": summary["usage"], "finish_reason": finish_reason},
            metadata={"ai": summary, "model_calls": router.attempts, "trace": trace},
        )


@register
class AgentExecutor(NodeExecutor):
    operation_id = "ai.agent"
    config_model = AgentConfig

    def has_side_effects(self, config: BaseModel, default: bool) -> bool:
        from app.ai.tools import get_tool_registry

        assert isinstance(config, AgentConfig)
        registry = get_tool_registry()
        return any(getattr(registry.get(t), "side_effects", False) for t in config.tools)

    async def execute(self, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext) -> NodeExecutionResult:
        assert isinstance(config, AgentConfig)
        router = ModelRouter(ctx, config.model, config.fallback_model, operation=self.operation_id)
        run = None
        try:
            await router.prepare()
            run = AgentRun(config, ctx, router)
            result = await run.run(config.task, config.inputs)
        except NodeExecutionError as exc:
            raise _attach(exc, ai=router.summary() if router._slots else None, model_calls=router.attempts,
                          agent_trace=run.trace if run else None) from None
        summary = router.summary()
        iterations = sum(1 for t in run.trace if t.get("type") == "model_call")
        ctx.logger.info(f"Agent finished with {summary['provider']}/{summary['model']} after {iterations} "
                        f"iteration(s) and {len(run.tool_summaries)} tool call(s)",
                        {"fallback_used": summary["fallback_used"], "usage": summary["usage"]})
        return NodeExecutionResult(
            output={"result": result, "provider": summary["provider"], "model": summary["model"],
                    "fallback_used": summary["fallback_used"], "fallback_reason": summary["fallback_reason"],
                    "iterations": iterations, "tool_calls": run.tool_summaries, "usage": summary["usage"]},
            metadata={"ai": summary, "agent_trace": run.trace, "model_calls": router.attempts},
        )
