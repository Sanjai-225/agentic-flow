"""Executor registration.

Maps registry operation ids to executor instances. A node is executable only
when the registry marks it ``executable`` AND an executor is registered here
(``tests/engine/test_registry_executors.py`` enforces both directions).
"""

from typing import Dict, Optional, Type

from app.engine.contracts import NodeExecutor

_EXECUTORS: Dict[str, NodeExecutor] = {}


def register(executor_cls: Type[NodeExecutor]) -> Type[NodeExecutor]:
    op = executor_cls.operation_id
    if op in _EXECUTORS:
        raise RuntimeError(f"Executor for '{op}' registered twice.")
    _EXECUTORS[op] = executor_cls()
    return executor_cls


def get_executor(operation_id: str) -> Optional[NodeExecutor]:
    _load_builtin_executors()
    return _EXECUTORS.get(operation_id)


def registered_operations() -> set[str]:
    _load_builtin_executors()
    return set(_EXECUTORS)


_loaded = False


def _load_builtin_executors() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from app.executors import ai, core, flow, http  # noqa: F401  (import registers executors)
