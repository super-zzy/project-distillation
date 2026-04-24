from __future__ import annotations

from datetime import datetime

from .db import db


class Project(db.Model):
    __tablename__ = "projects"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    # Use hash for uniqueness to avoid MySQL utf8mb4 index length limits.
    local_path = db.Column(db.Text, nullable=False)
    local_path_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    output_root = db.Column(db.String(1024), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Task(db.Model):
    """
    A durable task that can resume after restart.
    """

    __tablename__ = "tasks"

    id = db.Column(db.String(64), primary_key=True)  # uuid hex
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)

    status = db.Column(
        db.Enum("queued", "running", "paused", "completed", "failed", "stopped", name="task_status"),
        default="queued",
        nullable=False,
        index=True,
    )
    phase = db.Column(
        db.Enum("main", "commit", "branch", "summary", name="task_phase"),
        default="main",
        nullable=False,
        index=True,
    )

    message = db.Column(db.Text, nullable=True)
    progress_current = db.Column(db.Integer, default=0, nullable=False)
    progress_total = db.Column(db.Integer, default=0, nullable=False)

    # simple durable checkpoint for mainAgent
    cursor_branch = db.Column(db.String(255), nullable=True)
    cursor_commit = db.Column(db.String(64), nullable=True)

    error = db.Column(db.Text, nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class Commit(db.Model):
    __tablename__ = "commits"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)

    branch_name = db.Column(db.String(255), nullable=False, index=True)
    commit_sha = db.Column(db.String(64), nullable=False, index=True)
    commit_time = db.Column(db.DateTime, nullable=False, index=True)
    author = db.Column(db.String(255), nullable=True)
    subject = db.Column(db.Text, nullable=True)

    one_liner = db.Column(db.Text, nullable=True)
    ai_analysis = db.Column(db.Text, nullable=True)
    md_path = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.Enum("queued", "running", "completed", "failed", name="commit_status"),
        default="queued",
        nullable=False,
        index=True,
    )
    error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("project_id", "branch_name", "commit_sha", name="uq_project_branch_sha"),
    )


class Branch(db.Model):
    __tablename__ = "branches"

    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=False, index=True)

    name = db.Column(db.String(255), nullable=False, index=True)
    one_liner = db.Column(db.Text, nullable=True)
    ai_analysis = db.Column(db.Text, nullable=True)
    md_path = db.Column(db.Text, nullable=True)

    status = db.Column(
        db.Enum("queued", "running", "completed", "failed", name="branch_status"),
        default="queued",
        nullable=False,
        index=True,
    )
    error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("project_id", "name", name="uq_project_branch"),)


class TaskEvent(db.Model):
    __tablename__ = "task_events"

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    task_id = db.Column(db.String(64), db.ForeignKey("tasks.id"), nullable=False, index=True)

    level = db.Column(db.Enum("info", "warn", "error", name="event_level"), default="info", nullable=False)
    message = db.Column(db.Text, nullable=False)
    data_json = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class AiCall(db.Model):
    __tablename__ = "ai_calls"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    task_id = db.Column(db.String(64), db.ForeignKey("tasks.id"), nullable=True, index=True)
    project_id = db.Column(db.Integer, db.ForeignKey("projects.id"), nullable=True, index=True)

    # commit / branch / summary / other
    agent = db.Column(db.String(32), nullable=False, index=True)
    model = db.Column(db.String(128), nullable=False)

    # Best-effort linkage
    branch_name = db.Column(db.String(255), nullable=True, index=True)
    commit_sha = db.Column(db.String(64), nullable=True, index=True)

    prompt_id = db.Column(db.String(128), nullable=True)
    request_json = db.Column(db.Text, nullable=False)
    response_text = db.Column(db.Text, nullable=True)
    status = db.Column(db.Enum("ok", "error", name="ai_call_status"), nullable=False, index=True)
    error = db.Column(db.Text, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

