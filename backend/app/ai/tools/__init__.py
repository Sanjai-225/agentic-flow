"""Secure tool registry for the AI Agent.

Every tool has a stable id, a pydantic input model (``extra="forbid"``), an output model, a timeout,
side-effect and permission metadata, and a real async executor. Tools are grouped by ``ToolProvider``
so later milestones (e.g. Composio, Milestone 3) can plug in another provider without touching the
agent runtime.

Authorization is enforced in the backend at three levels (``ToolPolicy``):
1. the tool must exist in the registry (unknown names are rejected and never executed);
2. the tool must be in the node's explicit allowlist (``config.tools``; empty by default);
3. the deployment/user policy must permit it (``AGENT_DISABLED_TOOLS``, network tools switch,
   side-effecting tools require explicit opt-in).
The model never chooses its own permissions.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Literal, Optional, Protocol, Type

from pydantic import BaseModel

from app.core.config import get_settings

Permission = Literal["read_only", "network", "side_effect"]


@dataclass
class ToolContext:
    """What a tool may see: identity and limits, never credentials or other users' data."""

    user_id: str
    execution_id: str
    node_id: str
    cancel_event: asyncio.Event
    settings: Any = None


ToolExecutor = Callable[[BaseModel, ToolContext], Awaitable[Dict[str, Any]]]


@dataclass
class ToolDefinition:
    id: str
    name: str  # function name exposed to the model (identical to id; letters, digits, underscores)
    description: str
    input_model: Type[BaseModel]
    output_model: Type[BaseModel]
    execute: ToolExecutor
    timeout_seconds: float = 10.0
    side_effects: bool = False
    idempotent: bool = True
    permission: Permission = "read_only"
    provider: str = "builtin"
    tags: List[str] = field(default_factory=list)

    def model_schema(self) -> Dict[str, Any]:
        """OpenAI-style function schema; LangChain converts it for every provider in ``bind_tools``."""
        params = self.input_model.model_json_schema()
        params.pop("title", None)
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                  "parameters": params}}

    def public_view(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "description": self.description, "provider": self.provider,
                "permission": self.permission, "side_effects": self.side_effects,
                "timeout_seconds": self.timeout_seconds, "tags": self.tags,
                "input_schema": self.input_model.model_json_schema(),
                "output_schema": self.output_model.model_json_schema()}


class ToolProvider(Protocol):
    id: str

    def list_tools(self) -> List[ToolDefinition]:
        ...


class ToolRegistry:
    def __init__(self, providers: Iterable[ToolProvider]) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        for provider in providers:
            for tool in provider.list_tools():
                if tool.id in self._tools:
                    raise ValueError(f"Duplicate tool id {tool.id!r}")
                self._tools[tool.id] = tool

    def get(self, tool_id: str) -> Optional[ToolDefinition]:
        return self._tools.get(tool_id)

    def list_tools(self) -> List[ToolDefinition]:
        return list(self._tools.values())


class ToolPolicy:
    """Backend authorization for one agent node run (node allowlist + deployment policy)."""

    def __init__(self, allowed_ids: Iterable[str], allow_side_effects: bool = False) -> None:
        self.allowed = set(allowed_ids)
        self.allow_side_effects = allow_side_effects

    def denial_reason(self, tool: Optional[ToolDefinition], requested_name: str) -> Optional[str]:
        settings = get_settings()
        if tool is None:
            return f"Unknown tool '{requested_name}'. Only registered tools can be called."
        if tool.id not in self.allowed:
            return f"Tool '{tool.id}' is not enabled for this agent."
        if tool.id in settings.AGENT_DISABLED_TOOLS:
            return f"Tool '{tool.id}' is disabled on this server (AGENT_DISABLED_TOOLS)."
        if tool.permission == "network" and not settings.AGENT_ALLOW_NETWORK_TOOLS:
            return "Network tools are disabled on this server (AGENT_ALLOW_NETWORK_TOOLS=false)."
        if tool.side_effects and not self.allow_side_effects:
            return f"Tool '{tool.id}' changes external state and requires explicit authorization."
        return None


@lru_cache(maxsize=1)
def get_tool_registry() -> ToolRegistry:
    from app.ai.tools.builtin import BuiltinToolProvider

    return ToolRegistry([BuiltinToolProvider()])
