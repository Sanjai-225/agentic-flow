"""Request/response models for the workflow platform API."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=256)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _lower(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    id: str
    email: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class SaveWorkflowRequest(BaseModel):
    definition: Dict[str, Any] = Field(..., description="Canonical workflow JSON (schema v1 or v2).")


class ValidateWorkflowRequest(BaseModel):
    definition: Dict[str, Any]


class WorkflowSummary(BaseModel):
    id: str
    name: str
    description: str
    version: int
    has_webhook: bool
    active: bool = True
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    last_execution_status: Optional[str] = None


class WorkflowRecord(WorkflowSummary):
    definition: Dict[str, Any]
    validation: Dict[str, Any]


class RunWorkflowRequest(BaseModel):
    input: Any = Field(default_factory=dict, description="Payload delivered to the trigger node.")


class WorkflowActiveUpdate(BaseModel):
    active: bool


class FormInfo(BaseModel):
    node_id: str
    form_id: str
    url: str
    api_url: str
    enabled: bool
    workflow_active: bool


class ScheduleInfo(BaseModel):
    schedule_id: str
    node_id: str
    enabled: bool
    workflow_active: bool
    timezone: str
    spec: Dict[str, Any]
    next_run_at: Optional[datetime] = None
    last_run_at: Optional[datetime] = None
    last_execution_id: Optional[str] = None
    last_status: Optional[str] = None
    last_error: Optional[str] = None
    upcoming: List[datetime] = Field(default_factory=list)


class SchedulePreviewRequest(BaseModel):
    config: Dict[str, Any]
    count: int = Field(default=5, ge=1, le=20)


class WebhookInfo(BaseModel):
    token: str
    url: str
    method: str


class CredentialCreate(BaseModel):
    type: str
    name: str = Field(..., min_length=1, max_length=255)
    data: Dict[str, Any]


class CredentialUpdate(BaseModel):
    """Rename and/or replace secret fields; omitted or empty fields keep their stored value."""

    name: Optional[str] = Field(default=None, max_length=255)
    data: Optional[Dict[str, Any]] = None


class CredentialOut(BaseModel):
    id: str
    type: str
    name: str
    hints: Dict[str, str] = Field(default_factory=dict)
    provider: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CredentialTestResult(BaseModel):
    ok: bool
    message: str
    provider: Optional[str] = None
    category: Optional[str] = None
    models_available: List[str] = Field(default_factory=list)


class NodeExecutionOut(BaseModel):
    node_id: str
    operation: str
    label: str
    position: int
    status: str
    attempts: int
    inputs: Any = None
    output: Any = None
    error: Optional[Dict[str, Any]] = None
    route: Any = None
    metadata: Optional[Dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    duration_ms: Optional[float] = None


class ExecutionLogOut(BaseModel):
    node_id: Optional[str]
    level: str
    message: str
    data: Any = None
    ts: datetime


class ExecutionSummary(BaseModel):
    id: str
    workflow_id: str
    workflow_version: int
    status: str
    trigger_type: str
    created_at: Optional[datetime]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    duration_ms: Optional[float]
    error: Optional[Dict[str, Any]] = None


class ExecutionDetail(ExecutionSummary):
    correlation_id: str
    input: Any = None
    output: Any = None
    nodes: List[NodeExecutionOut]
    logs: List[ExecutionLogOut]
    workflow_definition: Optional[Dict[str, Any]] = None
