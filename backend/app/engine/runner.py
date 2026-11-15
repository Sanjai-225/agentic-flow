"""Sequential, deterministic workflow runner.

Semantics (Milestone 1):
- Nodes run one at a time in the planner's topological order.
- A node runs when at least one incoming edge is *active*. An edge is active
  when its source finished successfully (or failed with ``on_error=continue``)
  and the edge's ``source_port`` is among the ports the source routed to
  (``route``; default ``main``). Nodes with no active incoming edge are
  ``skipped`` — so only the selected If/Else branch executes.
- ``input`` for a node is the output of its single active predecessor, or a
  ``{node_id: output}`` object when several predecessors are active.
- Every state transition is persisted immediately (execution + node rows +
  logs), so runs are inspectable after completion, failure or a restart.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.errors import ErrorCategory, NodeError, NodeExecutionError
from app.db.models import Execution
from app.engine.contracts import (
    ExecutionContext,
    ExecutionLogger,
    LogEntry,
    NodeExecutionResult,
    NodeExecutor,
    NodeStatus,
    WorkflowStatus,
)
from app.engine.expressions import ResolutionScope, resolve_value
from app.engine.planner import ExecutionPlan, plan_workflow
from app.engine.redaction import redact, redact_text, scrub_secrets_in, storable
from app.executors import get_executor
from app.registry.node_registry import NodeRegistry, get_default_registry
from app.schemas.registry import NodeDefinition
from app.schemas.workflow import NodeSchema, WorkflowSchema
from app.services.credentials import DbCredentialAccessor, credential_ids_for_user
from app.services.execution_store import ExecutionStore

logger = logging.getLogger(__name__)


class ExecutionCancelled(Exception):
    pass


def utcnow() -> datetime:
    return datetime.now(UTC)


def _config_error(exc: ValidationError) -> NodeExecutionError:
    first = exc.errors()[0]
    loc = ".".join(str(p) for p in first["loc"]) or None
    return NodeExecutionError(
        ErrorCategory.SCHEMA_VALIDATION,
        f"Resolved config field '{loc or 'config'}' is invalid: {first['msg'].lower()}.",
        field=loc,
        details={"errors": [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]},
    )


class WorkflowRunner:
    def __init__(self, sessionmaker: Any, registry: Optional[NodeRegistry] = None,
                 settings: Optional[Settings] = None) -> None:
        self._sm = sessionmaker
        self._registry = registry or get_default_registry()
        self._settings = settings or get_settings()
        self._store = ExecutionStore(sessionmaker)

    # ------------------------------------------------------------------ run
    async def run(self, execution_id: str, cancel_event: Optional[asyncio.Event] = None) -> None:
        cancel_event = cancel_event or asyncio.Event()
        execution, definition = await self._store.load(execution_id)
        if execution is None:
            logger.error("Execution %s not found", execution_id)
            return
        if execution.status != WorkflowStatus.PENDING.value:
            logger.warning("Execution %s is %s; not starting", execution_id, execution.status)
            return
        try:
            await self._run(execution, definition, cancel_event)
        except asyncio.CancelledError:
            await self._finish(execution.id, WorkflowStatus.FAILED, error=NodeError(
                category=ErrorCategory.ENGINE_ERROR,
                message="Execution was interrupted because the server is shutting down.",
            ).with_defaults(), skip_reason="interrupted")
            raise
        except Exception as exc:  # engine bug: never leave a run stuck in 'running'
            logger.exception("Engine failure in execution %s", execution_id)
            await self._finish(execution.id, WorkflowStatus.FAILED, error=NodeError(
                category=ErrorCategory.ENGINE_ERROR,
                message="The workflow engine failed unexpectedly.",
                technical_detail=f"{type(exc).__name__}: {str(exc)[:300]}",
            ).with_defaults(), skip_reason="engine failure")

    async def _finish(self, execution_id: str, status: WorkflowStatus, *, output: Any = None,
                      error: Optional[NodeError] = None, skip_reason: Optional[str] = None) -> None:
        if skip_reason:
            await self._store.skip_pending_nodes(execution_id, skip_reason)
        await self._store.update_execution(
            execution_id, status=status.value, output=output,
            error=error.model_dump(mode="json") if error else None, finished_at=utcnow(),
        )

    async def _run(self, execution: Execution, definition: Optional[Dict[str, Any]],
                   cancel_event: asyncio.Event) -> None:
        exec_id = execution.id
        if definition is None:
            await self._finish(exec_id, WorkflowStatus.FAILED, error=NodeError(
                category=ErrorCategory.ENGINE_ERROR,
                message=f"Workflow version {execution.workflow_version} was not found.").with_defaults())
            return
        try:
            workflow = WorkflowSchema.model_validate(definition)
        except ValidationError as exc:
            await self._finish(exec_id, WorkflowStatus.FAILED, error=NodeError(
                category=ErrorCategory.SCHEMA_VALIDATION, message="The stored workflow definition is invalid.",
                technical_detail=str(exc)[:1000]).with_defaults())
            return

        async with self._sm() as session:
            cred_ids = await credential_ids_for_user(session, execution.user_id)
        plan = plan_workflow(workflow, self._registry, cred_ids)
        if not plan.valid:
            first = plan.errors[0]
            await self._finish(exec_id, WorkflowStatus.FAILED, error=NodeError(
                category=first.category, message=f"Workflow failed validation: {first.message}",
                node_id=first.node_id, field=first.field, suggestion=first.suggestion,
                details={"issues": [i.model_dump(mode="json") for i in plan.errors]}).with_defaults())
            return

        nodes = {n.id: n for n in workflow.nodes}
        await self._store.init_nodes(
            exec_id, [(nid, nodes[nid].operation or "", nodes[nid].label, pos) for pos, nid in enumerate(plan.order)]
        )
        await self._store.update_execution(exec_id, status=WorkflowStatus.RUNNING.value, started_at=utcnow())
        await self._store.add_logs(exec_id, [LogEntry("info", f"Execution started ({execution.trigger_type} trigger, "
                                                      f"workflow v{execution.workflow_version}, "
                                                      f"{len(plan.order)} nodes)")])

        outputs: Dict[str, Any] = {}
        statuses: Dict[str, str] = {nid: NodeStatus.PENDING.value for nid in plan.order}
        active_edges: Set[str] = set()
        deadline = time.monotonic() + self._settings.EXECUTION_MAX_DURATION_SECONDS
        failure: Optional[NodeError] = None
        cancelled = False
        base_scope = {
            "execution": {"id": exec_id, "trigger_type": execution.trigger_type},
            "workflow": {"id": workflow.workflow_id, "version": execution.workflow_version,
                         "name": workflow.workflow_name},
        }

        for nid in plan.order:
            node = nodes[nid]
            if nid in plan.body_owner:
                continue  # loop-body nodes run once per item inside _run_loop
            if cancel_event.is_set():
                cancelled = True
                break
            if time.monotonic() > deadline:
                failure = NodeError(category=ErrorCategory.TIMEOUT, node_id=nid,
                                    message=f"Execution exceeded the maximum duration of "
                                            f"{self._settings.EXECUTION_MAX_DURATION_SECONDS}s.").with_defaults()
                break

            inputs_by_port: Dict[str, List[Dict[str, Any]]] = {}
            if nid == plan.trigger_node_id:
                upstream: Any = execution.input if execution.input is not None else {}
            else:
                active_in = [e for e in plan.incoming.get(nid, []) if e.id in active_edges]
                if not active_in:
                    statuses[nid] = NodeStatus.SKIPPED.value
                    await self._store.update_node(exec_id, nid, status=NodeStatus.SKIPPED.value,
                                                  node_metadata={"skip_reason": "No active incoming connection "
                                                                 "(branch not taken)."}, finished_at=utcnow())
                    for body_id in plan.loop_bodies.get(nid, []):
                        statuses[body_id] = NodeStatus.SKIPPED.value
                        await self._store.update_node(exec_id, body_id, status=NodeStatus.SKIPPED.value,
                                                      node_metadata={"skip_reason": "Its loop was skipped."},
                                                      finished_at=utcnow())
                    continue
                preds: List[str] = []
                for e in active_in:
                    if e.source not in preds:
                        preds.append(e.source)
                upstream = outputs[preds[0]] if len(preds) == 1 else {p: outputs[p] for p in preds}
                for e in active_in:
                    inputs_by_port.setdefault(e.target_port or "main", []).append(
                        {"source": e.source, "edge": e.id, "output": outputs[e.source]})

            scope = ResolutionScope(
                node_outputs=outputs, node_statuses=statuses, all_node_ids=set(nodes),
                ancestors=plan.ancestors.get(nid, set()), trigger_node_id=plan.trigger_node_id,
                upstream=upstream, **base_scope,
            )
            definition_ = plan.definitions[nid]
            result = await self._run_node(execution, workflow, node, definition_, scope, cancel_event,
                                          inputs_by_port=inputs_by_port)
            statuses[nid] = result.status.value

            if result.status == NodeStatus.SUCCESS and nid in plan.loop_bodies:
                result = await self._run_loop(execution, workflow, plan, node, result, outputs, statuses,
                                              base_scope, cancel_event, deadline)
                statuses[nid] = result.status.value
            if result.error is not None and result.error.category == ErrorCategory.CANCELLED:
                cancelled = True
                break
            if result.status == NodeStatus.SUCCESS:
                outputs[nid] = result.output
                ports = result.route if result.route is not None else ["main"]
            elif node.on_error == "continue":
                outputs[nid] = {"error": result.error.model_dump(mode="json") if result.error else None}
                ports = ["main"]
            else:
                failure = result.error
                break
            for edge in plan.outgoing.get(nid, []):
                if edge.source_port in ports:
                    active_edges.add(edge.id)

        if cancelled:
            await self._store.add_logs(exec_id, [LogEntry("warning", "Execution cancelled by user.")])
            await self._finish(exec_id, WorkflowStatus.CANCELLED, error=NodeError(
                category=ErrorCategory.CANCELLED, message="Execution was cancelled.").with_defaults(),
                skip_reason="execution cancelled")
            return
        if failure is not None:
            await self._finish(exec_id, WorkflowStatus.FAILED, error=failure,
                               skip_reason="an upstream node failed")
            return

        end_ids = [nid for nid in plan.order
                   if nodes[nid].operation == "core.end" and statuses[nid] == NodeStatus.SUCCESS.value]
        if len(end_ids) == 1:
            final = outputs[end_ids[0]]
        elif end_ids:
            final = {nid: outputs[nid] for nid in end_ids}
        else:
            ran = [nid for nid in plan.order if nid in outputs]
            final = outputs[ran[-1]] if ran else None
        await self._finish(exec_id, WorkflowStatus.COMPLETED, output=final)

    # ----------------------------------------------------------------- loop
    async def _run_loop(self, execution: Execution, workflow: WorkflowSchema, plan: ExecutionPlan,
                        loop_node: NodeSchema, loop_result: NodeExecutionResult, outputs: Dict[str, Any],
                        statuses: Dict[str, str], base_scope: Dict[str, Any], cancel_event: asyncio.Event,
                        deadline: float) -> NodeExecutionResult:
        """Run the loop body once per item; return the loop node's final result (routes to 'done').

        Each iteration gets its own copy of the node outputs, so body nodes see the current item's data
        ({{item}}, {{loop.index}}, {{nodes.<body_id>.output}}) and nothing leaks between iterations. Body
        nodes run through ``_run_node`` (retries, timeouts, redaction, persistence); their rows keep the last
        iteration plus a capped per-iteration summary in ``metadata.iterations``.
        """
        exec_id = execution.id
        loop_id = loop_node.id
        body = plan.loop_bodies[loop_id]
        body_set = set(body)
        nodes = {n.id: n for n in workflow.nodes}
        items = list((loop_result.output or {}).get("items") or [])
        config = loop_node.config if isinstance(loop_node.config, dict) else {}
        stop_on_error = config.get("on_item_error", "stop") != "continue"
        try:
            loop_timeout = float(config.get("timeout_seconds", 300))
        except (TypeError, ValueError):
            loop_timeout = 300.0
        loop_deadline = min(deadline, time.monotonic() + loop_timeout)
        terminals = [nid for nid in body if not any(e.target in body_set for e in plan.outgoing.get(nid, []))]
        results: List[Any] = []
        errors: List[Dict[str, Any]] = []
        history: Dict[str, List[Dict[str, Any]]] = {nid: [] for nid in body}
        last_status: Dict[str, str] = {nid: NodeStatus.SKIPPED.value for nid in body}
        failure: Optional[NodeError] = None
        count = len(items)
        await self._store.add_logs(exec_id, [LogEntry("info", f"Loop '{loop_node.label}' starting {count} "
                                                      f"iteration(s)", node_id=loop_id)])

        for index, item in enumerate(items):
            if cancel_event.is_set():
                failure = NodeError(category=ErrorCategory.CANCELLED, message="Execution was cancelled.")
                break
            if time.monotonic() > loop_deadline:
                failure = NodeError(category=ErrorCategory.TIMEOUT, node_id=loop_id, field="timeout_seconds",
                                    message=f"The loop did not finish within its time limit "
                                            f"({len(results)} of {count} items done).").with_defaults()
                break
            iter_outputs: Dict[str, Any] = dict(outputs)
            iter_statuses: Dict[str, str] = dict(statuses)
            active: Set[str] = {e.id for e in plan.outgoing.get(loop_id, []) if e.source_port == "item"}
            loop_ctx = {"item": item, "loop": {"index": index, "count": count, "item": item,
                                               "is_first": index == 0, "is_last": index == count - 1}}
            item_error: Optional[Dict[str, Any]] = None
            for nid in body:
                node = nodes[nid]
                active_in = [e for e in plan.incoming.get(nid, []) if e.id in active]
                if not active_in:
                    iter_statuses[nid] = NodeStatus.SKIPPED.value
                    history[nid].append({"index": index, "status": "skipped"})
                    continue
                preds: List[str] = []
                inputs_by_port: Dict[str, List[Dict[str, Any]]] = {}
                for e in active_in:
                    value = item if e.source == loop_id else iter_outputs[e.source]
                    if e.source not in preds:
                        preds.append(e.source)
                    inputs_by_port.setdefault(e.target_port or "main", []).append(
                        {"source": e.source, "edge": e.id, "output": value})
                pred_values = {p: (item if p == loop_id else iter_outputs[p]) for p in preds}
                upstream = pred_values[preds[0]] if len(preds) == 1 else pred_values
                scope = ResolutionScope(
                    node_outputs=iter_outputs, node_statuses=iter_statuses, all_node_ids=set(nodes),
                    ancestors=plan.ancestors.get(nid, set()), trigger_node_id=plan.trigger_node_id,
                    upstream=upstream, extra=loop_ctx, **base_scope,
                )
                result = await self._run_node(execution, workflow, node, plan.definitions[nid], scope, cancel_event,
                                              inputs_by_port=inputs_by_port)
                iter_statuses[nid] = result.status.value
                last_status[nid] = result.status.value
                entry: Dict[str, Any] = {"index": index, "status": result.status.value}
                if result.error is not None and result.error.category == ErrorCategory.CANCELLED:
                    failure = result.error
                    history[nid].append(entry)
                    break
                if result.status == NodeStatus.SUCCESS:
                    iter_outputs[nid] = result.output
                    entry["output_preview"] = storable(result.output)
                    ports = result.route if result.route is not None else ["main"]
                elif node.on_error == "continue":
                    iter_outputs[nid] = {"error": result.error.model_dump(mode="json") if result.error else None}
                    ports = ["main"]
                else:
                    entry["error"] = result.error.message if result.error else "failed"
                    history[nid].append(entry)
                    item_error = {"index": index, "node_id": nid,
                                  "category": result.error.category.value if result.error else None,
                                  "message": result.error.message if result.error else "Node failed."}
                    break
                history[nid].append(entry)
                for edge in plan.outgoing.get(nid, []):
                    if edge.source_port in ports:
                        active.add(edge.id)
            if failure is not None:
                break
            if item_error is not None:
                errors.append(item_error)
                results.append(None)
                if stop_on_error:
                    failure = NodeError(
                        category=ErrorCategory.NODE_EXECUTION, node_id=loop_id,
                        message=f"Item {index} failed at node '{item_error['node_id']}': {item_error['message']}",
                        suggestion="Fix the failing item, or set 'When an item fails' to 'continue'.",
                        details={"errors": errors}).with_defaults()
                    break
                continue
            ran = [t for t in terminals if t in iter_outputs and iter_statuses.get(t) == NodeStatus.SUCCESS.value]
            results.append(iter_outputs[ran[0]] if len(ran) == 1 else {t: iter_outputs[t] for t in ran} or None)

        # Persist a per-node summary of every iteration (capped) and the overall body node status.
        for nid in body:
            ran = [h for h in history[nid] if h["status"] != "skipped"]
            if not ran:
                status = NodeStatus.SKIPPED.value
            elif any(h["status"] == NodeStatus.FAILED.value for h in ran):
                status = NodeStatus.FAILED.value
            else:
                status = last_status[nid]
            statuses[nid] = status
            meta = {"loop_id": loop_id, "iteration_count": len(ran), "iterations": history[nid][:100],
                    "iterations_truncated": len(history[nid]) > 100}
            if not ran:
                meta["skip_reason"] = "The loop had no items." if not items else "Not reached in any iteration."
            await self._store.update_node(exec_id, nid, status=status, node_metadata=meta, finished_at=utcnow())

        failed_indexes = {e["index"] for e in errors}
        succeeded = sum(1 for i in range(len(results)) if i not in failed_indexes)
        final = {"results": results, "count": count, "succeeded": succeeded, "failed": len(errors),
                 "errors": errors, "items": items}
        status = NodeStatus.FAILED if failure is not None else NodeStatus.SUCCESS
        await self._store.update_node(exec_id, loop_id, status=status.value,
                                      output=final if failure is None else None,
                                      error=failure.model_dump(mode="json") if failure else None,
                                      node_metadata={"loop": True, "count": count, "succeeded": succeeded,
                                                     "failed": len(errors)},
                                      route=["done"] if failure is None else None, finished_at=utcnow())
        await self._store.add_logs(exec_id, [LogEntry(
            "info" if failure is None else "error",
            f"Loop '{loop_node.label}' finished: {succeeded} succeeded, {len(errors)} failed of {count}",
            node_id=loop_id)])
        if failure is not None:
            return NodeExecutionResult(status=NodeStatus.FAILED, error=failure)
        return NodeExecutionResult(output=final, route=["done"], metadata={"loop": True})

    # ----------------------------------------------------------------- node
    async def _run_node(self, execution: Execution, workflow: WorkflowSchema, node: NodeSchema,
                        definition: NodeDefinition, scope: ResolutionScope,
                        cancel_event: asyncio.Event,
                        inputs_by_port: Optional[Dict[str, List[Dict[str, Any]]]] = None) -> NodeExecutionResult:
        exec_id = execution.id
        executor = get_executor(definition.operation_id)
        assert executor is not None  # guaranteed by the planner
        retry = node.retry or definition.default_retry
        timeout = float(node.timeout_seconds or definition.default_timeout_seconds)
        lazy = set(definition.lazy_config_fields)
        result = NodeExecutionResult(status=NodeStatus.FAILED)
        attempt_errors: List[Dict[str, Any]] = []

        def resolver(value: Any, field: str, extra: Optional[Dict[str, Any]] = None) -> Any:
            sub = scope if not extra else ResolutionScope(**{**scope.__dict__, "extra": {**scope.extra, **extra}})
            return resolve_value(value, sub, field)

        for attempt in range(1, retry.max_attempts + 1):
            node_logger = ExecutionLogger(node.id)
            started_at = utcnow()
            t0 = time.perf_counter()
            await self._store.update_node(exec_id, node.id, status=NodeStatus.RUNNING.value, attempts=attempt,
                                          started_at=started_at)
            recorded_inputs: Dict[str, Any] = {"upstream": scope.upstream}
            side_effects = definition.side_effects
            node_secrets: set[str] = set()

            async def usage_sink(record: Dict[str, Any], _node_id: str = node.id) -> None:
                await self._store.add_ai_usage(exec_id, execution.user_id, execution.workflow_id, _node_id, record)
            try:
                resolved_config = resolve_value(node.config, scope, "", skip_keys=lazy)
                resolved_inputs = resolve_value(node.inputs, scope, "inputs")
                recorded_inputs.update({"config": redact(resolved_config), "inputs": redact(resolved_inputs)})
                try:
                    config: BaseModel = (definition.config_model or BaseModel).model_validate(resolved_config)
                except ValidationError as exc:
                    raise _config_error(exc) from exc
                side_effects = executor.has_side_effects(config, definition.side_effects)
                ctx = ExecutionContext(
                    workflow_id=workflow.workflow_id, workflow_version=execution.workflow_version,
                    execution_id=exec_id, node_id=node.id, operation=definition.operation_id,
                    user_id=execution.user_id, correlation_id=execution.correlation_id, upstream=scope.upstream,
                    state=dict(scope.node_outputs), credentials=DbCredentialAccessor(self._sm, execution.user_id),
                    logger=node_logger, cancel_event=cancel_event, timeout_seconds=timeout, attempt=attempt,
                    resolve=resolver, settings=self._settings, usage_sink=usage_sink, secrets=node_secrets,
                    inputs_by_port=inputs_by_port or {},
                )
                result = await self._invoke(executor, config, resolved_inputs, ctx, timeout, cancel_event)
            except NodeExecutionError as exc:
                result = NodeExecutionResult(status=NodeStatus.FAILED, error=exc.error)
            except ExecutionCancelled:
                result = NodeExecutionResult(status=NodeStatus.FAILED, error=NodeError(
                    category=ErrorCategory.CANCELLED, message="Node was cancelled while running.").with_defaults())
            except TimeoutError:
                result = NodeExecutionResult(status=NodeStatus.FAILED, error=NodeError(
                    category=ErrorCategory.TIMEOUT, retryable=True,
                    message=f"Node exceeded its {timeout:g}s timeout.").with_defaults())
            except Exception as exc:  # executor bug or unexpected library error
                logger.exception("Unexpected error in node %s", node.id)
                result = NodeExecutionResult(status=NodeStatus.FAILED, error=NodeError(
                    category=ErrorCategory.NODE_EXECUTION,
                    message=f"The node failed with an unexpected {type(exc).__name__}.",
                    technical_detail=redact_text(str(exc)[:500])).with_defaults())

            duration_ms = round((time.perf_counter() - t0) * 1000, 2)
            if node_secrets:
                # Never persist secrets resolved during this node (e.g. provider API keys) - even if a provider
                # echoed them back in an error, a tool result or a model response.
                result.output = scrub_secrets_in(result.output, node_secrets)
                result.metadata = scrub_secrets_in(result.metadata, node_secrets)
                if result.error is not None:
                    result.error = result.error.model_copy(update={
                        "message": scrub_secrets_in(result.error.message, node_secrets),
                        "technical_detail": scrub_secrets_in(result.error.technical_detail, node_secrets),
                        "details": scrub_secrets_in(result.error.details, node_secrets)})
                for entry in node_logger.entries:
                    entry.message = scrub_secrets_in(entry.message, node_secrets)
                    entry.data = scrub_secrets_in(entry.data, node_secrets)
            if result.error is not None:
                result.status = NodeStatus.FAILED
                result.error.node_id = node.id
                result.error.operation = definition.operation_id
                result.error.details.setdefault("label", node.label)
                result.error.details.setdefault("correlation_id", execution.correlation_id)
                result.error.with_defaults()
                attempt_errors.append({"attempt": attempt, "category": result.error.category.value,
                                       "message": result.error.message})
                node_logger.error(result.error.message, {"category": result.error.category.value,
                                                         "attempt": attempt})
            metadata = {**result.metadata, "attempt": attempt, "max_attempts": retry.max_attempts,
                        "side_effects": side_effects}
            if attempt_errors:
                metadata["attempt_errors"] = attempt_errors

            will_retry = False
            if result.status == NodeStatus.FAILED and result.error is not None:
                err = result.error
                if err.retryable and attempt < retry.max_attempts and err.category != ErrorCategory.CANCELLED:
                    if side_effects and not definition.idempotent:
                        node_logger.warning("Automatic retry blocked: this operation changes external state and has "
                                            "no idempotency guarantee, so a retry could duplicate the action.")
                        metadata["retry_blocked"] = "side_effects_without_idempotency"
                    else:
                        will_retry = True

            await self._store.update_node(
                exec_id, node.id,
                status=(NodeStatus.RUNNING if will_retry else result.status).value,
                inputs=recorded_inputs,
                output=result.output if result.status == NodeStatus.SUCCESS else None,
                error=result.error.model_dump(mode="json") if result.error else None,
                route=result.route, node_metadata=metadata,
                finished_at=None if will_retry else utcnow(), duration_ms=duration_ms,
            )
            await self._store.add_logs(exec_id, node_logger.entries)

            if not will_retry:
                return result
            delay = min(retry.max_backoff_seconds,
                        retry.backoff_seconds * (retry.backoff_multiplier ** (attempt - 1)))
            delay *= random.uniform(0.8, 1.2)
            await self._store.add_logs(exec_id, [LogEntry(
                "info", f"Retrying in {delay:.2f}s (attempt {attempt + 1}/{retry.max_attempts})", node_id=node.id)])
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=delay)
                return NodeExecutionResult(status=NodeStatus.FAILED, error=NodeError(
                    category=ErrorCategory.CANCELLED, message="Cancelled while waiting to retry.").with_defaults())
            except TimeoutError:
                pass
        return result

    @staticmethod
    async def _invoke(executor: NodeExecutor, config: BaseModel, inputs: Dict[str, Any], ctx: ExecutionContext,
                      timeout: float, cancel_event: asyncio.Event) -> NodeExecutionResult:
        task = asyncio.create_task(executor.execute(config, inputs, ctx))
        cancel_wait = asyncio.create_task(cancel_event.wait())
        try:
            done, _ = await asyncio.wait({task, cancel_wait}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        except asyncio.CancelledError:
            task.cancel()
            cancel_wait.cancel()
            raise
        if task in done:
            cancel_wait.cancel()
            return task.result()
        task.cancel()
        cancel_wait.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
        if cancel_wait in done:
            raise ExecutionCancelled()
        raise TimeoutError()


__all__ = ["WorkflowRunner", "ExecutionPlan"]
