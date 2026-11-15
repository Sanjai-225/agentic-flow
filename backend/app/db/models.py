"""SQLAlchemy ORM models. Every user-owned row carries ``user_id``; repositories filter on it."""

from __future__ import annotations

import uuid
from datetime import datetime, UTC
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, Any: JSON}


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("usr"))
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("wf"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    webhook_token_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    versions: Mapped[list[WorkflowVersion]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", passive_deletes=True
    )


class WorkflowVersion(Base):
    __tablename__ = "workflow_versions"
    __table_args__ = (UniqueConstraint("workflow_id", "version", name="uq_workflow_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workflow: Mapped[Workflow] = relationship(back_populates="versions")


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (Index("ix_executions_workflow_created", "workflow_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("exe"))
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id", ondelete="CASCADE"), index=True)
    workflow_version: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    trigger_type: Mapped[str] = mapped_column(String(32), default="manual")
    input: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    output: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class NodeExecution(Base):
    __tablename__ = "node_executions"
    __table_args__ = (UniqueConstraint("execution_id", "node_id", name="uq_node_execution"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[str] = mapped_column(String(255))
    operation: Mapped[str] = mapped_column(String(255))
    label: Mapped[str] = mapped_column(String(255), default="")
    position: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    inputs: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    output: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    error: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    route: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    node_metadata: Mapped[Optional[dict[str, Any]]] = mapped_column("metadata", JSON, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[Optional[float]] = mapped_column(nullable=True)


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[str] = mapped_column(ForeignKey("executions.id", ondelete="CASCADE"), index=True)
    node_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Credential(Base):
    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cred"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    encrypted_data: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
