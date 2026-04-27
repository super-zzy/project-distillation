from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from .db import db
from .models import Project, SkillDraft, Task, TaskEvent
from .utils import get_logger
from .worker import emit, ensure_task_runner, new_task_id

api = Blueprint("api", __name__)
log = get_logger("routes")

def _path_hash(p: str) -> str:
    norm = str(Path(p).resolve()).replace("\\", "/").lower()
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()

@api.post("/pick_folder")
def pick_folder():
    """
    Open a native folder picker dialog on the server machine (local usage).

    Note: Browsers cannot provide an absolute local path for security reasons.
    Prefer platform-native pickers (macOS: osascript) and fall back to Tk if available.
    """
    try:
        import sys

        # macOS: use AppleScript to open a native folder picker without tkinter.
        if sys.platform == "darwin":
            import subprocess

            script = 'POSIX path of (choose folder with prompt "选择本地 Git 项目目录（需包含 .git ）")'
            cp = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                check=False,
            )
            if cp.returncode == 0:
                return jsonify({"path": (cp.stdout or "").strip()})
            # User cancelled => typically exit code 1, stderr contains "User canceled."
            if "canceled" in (cp.stderr or "").lower():
                return jsonify({"path": ""})
            raise RuntimeError((cp.stderr or cp.stdout or "osascript failed").strip())

        # Fallback: Tk folder picker (requires _tkinter).
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        try:
            root.attributes("-topmost", True)
        except Exception:  # noqa: BLE001
            pass
        path = filedialog.askdirectory(title="选择本地 Git 项目目录（需包含 .git）")
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass

        return jsonify({"path": (path or "").strip()})
    except Exception as e:  # noqa: BLE001
        log.exception("pick_folder failed: %s", e)
        return (
            jsonify(
                {
                    "error": "folder picker unavailable. On macOS it requires `osascript`; otherwise it may require tkinter.",
                    "detail": str(e),
                }
            ),
            500,
        )


@api.get("/tasks/active")
def list_active_tasks():
    """
    List tasks that are not finished, newest first.
    Used by web page to re-attach after refresh/restart.
    """
    tasks = Task.query.filter(Task.status.in_(("queued", "running", "paused"))).all()
    # Prefer the single running task (requirement: only one running allowed).
    tasks.sort(key=lambda t: 0 if t.status == "running" else 1)
    tasks = tasks[:20]

    def last_event_id(tid: str) -> int:
        e = TaskEvent.query.filter_by(task_id=tid).order_by(TaskEvent.id.desc()).first()
        return int(e.id) if e else 0

    return jsonify(
        {
            "tasks": [
                {
                    "id": t.id,
                    "project_id": t.project_id,
                    "status": t.status,
                    "phase": t.phase,
                    "message": t.message,
                    "progress": {"current": t.progress_current, "total": t.progress_total},
                    "error": t.error,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                    "last_event_id": last_event_id(t.id),
                }
                for t in tasks
            ]
        }
    )


@api.get("/tasks/recent")
def list_recent_tasks():
    """
    Recent tasks including completed/failed/stopped.
    """
    tasks = Task.query.order_by(Task.created_at.desc()).limit(50).all()

    def last_event_id(tid: str) -> int:
        e = TaskEvent.query.filter_by(task_id=tid).order_by(TaskEvent.id.desc()).first()
        return int(e.id) if e else 0

    return jsonify(
        {
            "tasks": [
                {
                    "id": t.id,
                    "project_id": t.project_id,
                    "status": t.status,
                    "phase": t.phase,
                    "message": t.message,
                    "progress": {"current": t.progress_current, "total": t.progress_total},
                    "error": t.error,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "updated_at": t.updated_at.isoformat() if t.updated_at else None,
                    "last_event_id": last_event_id(t.id),
                }
                for t in tasks
            ]
        }
    )


@api.post("/analyze")
def analyze_project():
    # Enforce single running task in system.
    running = Task.query.filter_by(status="running").order_by(Task.updated_at.desc()).first()
    if running:
        log.warning("analyze_project blocked: existing running task=%s", running.id)
        return jsonify({"error": "a task is already running", "task_id": running.id}), 409

    data = request.get_json(force=True, silent=True) or {}
    project_path = (data.get("project_path") or os.getenv("PROJECT_PATH", "") or "").strip()
    if not project_path:
        log.warning("analyze_project missing project_path")
        return jsonify({"error": "project_path required (or set PROJECT_PATH in .env)"}), 400

    p = Path(project_path)
    if not p.exists():
        log.warning("analyze_project path not found: %s", project_path)
        return jsonify({"error": f"path not found: {project_path}"}), 400
    if not (p / ".git").exists():
        log.warning("analyze_project missing .git: %s", project_path)
        return jsonify({"error": "project_path must contain .git"}), 400

    project_name = p.name
    output_root = os.getenv("OUTPUT_ROOT", "./distilled")
    lp = str(p.resolve())
    lph = _path_hash(lp)

    project = Project.query.filter_by(local_path_hash=lph).first()
    if not project:
        project = Project(name=project_name, local_path=lp, local_path_hash=lph, output_root=output_root)
        db.session.add(project)
        db.session.commit()
        log.info("created project id=%s name=%s path=%s", project.id, project.name, project.local_path)
    else:
        log.info("reuse project id=%s name=%s path=%s", project.id, project.name, project.local_path)

    task_id = new_task_id()
    task = Task(id=task_id, project_id=project.id, status="queued", phase="main", message="queued")
    db.session.add(task)
    db.session.commit()
    emit(task_id, f"创建任务：{task_id}", data={"project": project.name, "path": project.local_path})
    log.info("created task id=%s project_id=%s", task_id, project.id)

    # Ensure the task is picked up even if global worker loop is idle.
    ensure_task_runner(current_app._get_current_object(), task_id)

    return jsonify({"task_id": task_id, "project": {"id": project.id, "name": project.name}})


@api.get("/tasks/<task_id>")
def get_task(task_id: str):
    task = Task.query.get(task_id)
    if not task:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "id": task.id,
            "project_id": task.project_id,
            "status": task.status,
            "phase": task.phase,
            "message": task.message,
            "progress": {"current": task.progress_current, "total": task.progress_total},
            "error": task.error,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }
    )


@api.post("/tasks/<task_id>/pause")
def pause_task(task_id: str):
    task = Task.query.get(task_id)
    if not task:
        log.warning("pause_task not found: %s", task_id)
        return jsonify({"error": "not found"}), 404
    if task.status in ("completed", "failed"):
        log.warning("pause_task invalid status task=%s status=%s", task_id, task.status)
        return jsonify({"error": f"cannot pause task in status {task.status}"}), 400
    task.status = "paused"
    db.session.add(task)
    db.session.commit()
    emit(task_id, "任务已暂停")
    return jsonify({"ok": True})


@api.post("/tasks/<task_id>/resume")
def resume_task(task_id: str):
    task = Task.query.get(task_id)
    if not task:
        log.warning("resume_task not found: %s", task_id)
        return jsonify({"error": "not found"}), 404
    if task.status in ("completed", "failed"):
        log.warning("resume_task invalid status task=%s status=%s", task_id, task.status)
        return jsonify({"error": f"cannot resume task in status {task.status}"}), 400
    task.status = "running"
    db.session.add(task)
    db.session.commit()
    emit(task_id, "任务已恢复")
    return jsonify({"ok": True})


@api.post("/tasks/<task_id>/stop")
def stop_task(task_id: str):
    task = Task.query.get(task_id)
    if not task:
        log.warning("stop_task not found: %s", task_id)
        return jsonify({"error": "not found"}), 404
    if task.status in ("completed", "failed", "stopped"):
        return jsonify({"error": f"cannot stop task in status {task.status}"}), 400
    task.status = "stopped"
    task.message = "stopped by user"
    db.session.add(task)
    db.session.commit()
    emit(task_id, "任务已停止", level="warn")
    log.info("task stopped: %s", task_id)
    return jsonify({"ok": True})


@api.delete("/tasks/<task_id>/purge")
def purge_task(task_id: str):
    """
    Permanently delete a task and its task-scoped data.

    Deletes:
    - task_events where task_id
    - ai_calls where task_id
    - task row

    Note: commits/branches are project-level in current design, not task-scoped.
    """
    from .models import AiCall  # local import to avoid circular issues

    task = Task.query.get(task_id)
    if not task:
        return jsonify({"error": "not found"}), 404

    if task.status == "running":
        return jsonify({"error": "cannot purge a running task; pause/stop first"}), 400

    # delete children first
    ev_count = TaskEvent.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    ai_count = AiCall.query.filter_by(task_id=task_id).delete(synchronize_session=False)
    db.session.delete(task)
    db.session.commit()

    log.warning("purged task=%s events=%s ai_calls=%s", task_id, ev_count, ai_count)
    return jsonify({"ok": True, "deleted": {"task_events": ev_count, "ai_calls": ai_count, "task": 1}})


@api.get("/progress/<task_id>")
def sse_progress(task_id: str):
    """
    SSE stream, backed by TaskEvent table so it can resume after restart.
    Client can pass ?last_id=<int> to continue from a specific event id.
    """

    # Read request args inside request context; the generator may outlive it.
    last_id = request.args.get("last_id", type=int) or 0

    def gen():
        nonlocal last_id
        while True:
            task = Task.query.get(task_id)
            if not task:
                yield _sse("error", {"message": "task not found"})
                return

            events = (
                TaskEvent.query.filter(TaskEvent.task_id == task_id, TaskEvent.id > last_id)
                .order_by(TaskEvent.id.asc())
                .limit(200)
                .all()
            )
            for e in events:
                last_id = e.id
                payload = {
                    "id": e.id,
                    "level": e.level,
                    "message": e.message,
                    "data": json.loads(e.data_json) if e.data_json else None,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                    "task": {
                        "status": task.status,
                        "phase": task.phase,
                        "message": task.message,
                        "progress": {"current": task.progress_current, "total": task.progress_total},
                        "error": task.error,
                    },
                }
                yield _sse("event", payload, event_id=e.id)

            if task.status in ("completed", "failed"):
                yield _sse(
                    "done",
                    {"status": task.status, "error": task.error},
                )
                return

            time.sleep(0.8)

    return Response(stream_with_context(gen()), mimetype="text/event-stream")


@api.get("/skill/latest")
def get_latest_skill():
    project_id = request.args.get("project_id", type=int)
    if not project_id:
        return jsonify({"error": "project_id required"}), 400
    sd = SkillDraft.query.filter_by(project_id=project_id).order_by(SkillDraft.version.desc(), SkillDraft.id.desc()).first()
    if not sd:
        return jsonify({"error": "not found"}), 404
    return jsonify(
        {
            "id": sd.id,
            "project_id": sd.project_id,
            "task_id": sd.task_id,
            "version": sd.version,
            "content_md": sd.content_md,
            "md_path": sd.md_path,
            "created_at": sd.created_at.isoformat() if sd.created_at else None,
        }
    )


@api.post("/skill/iterate")
def iterate_skill():
    data = request.get_json(force=True, silent=True) or {}
    project_id = data.get("project_id")
    feedback = (data.get("feedback") or "").strip()
    task_id = (data.get("task_id") or "").strip() or None
    if not project_id:
        return jsonify({"error": "project_id required"}), 400
    if not feedback:
        return jsonify({"error": "feedback required"}), 400

    sd = SkillDraft.query.filter_by(project_id=int(project_id)).order_by(SkillDraft.version.desc(), SkillDraft.id.desc()).first()
    if not sd:
        return jsonify({"error": "no skill draft found; run analyze first"}), 404

    # Emit via task stream if available, so the homepage UI can see it.
    if task_id:
        emit(task_id, f"skillAgent：收到反馈，开始迭代（基于 v{sd.version}）")

    try:
        from .ai_client import AiClient

        system = "你是 Cursor Skill 的编辑器。你会根据用户反馈对 SKILL.md 做增量改写：保持结构清晰、步骤可执行、不要编造项目不存在的命令/文件。只输出 Markdown 正文，不要代码块围栏。"
        user = (
            "这是当前的 SKILL.md：\n\n"
            f"{sd.content_md}\n\n"
            "用户反馈/新要求：\n"
            f"{feedback}\n\n"
            "请输出更新后的完整 SKILL.md（覆盖式输出）。"
        )
        ai = AiClient()
        new_text = ai.chat(
            system=system,
            user=user,
            meta={
                "task_id": task_id,
                "project_id": int(project_id),
                "agent": "skill",
                "prompt_id": "skill_iterate.v1",
            },
        )

        version = (db.session.query(db.func.max(SkillDraft.version)).filter(SkillDraft.project_id == int(project_id)).scalar() or 0) + 1
        new_sd = SkillDraft(
            task_id=task_id,
            project_id=int(project_id),
            version=int(version),
            content_md=new_text,
            md_path=sd.md_path,
        )
        db.session.add(new_sd)
        db.session.commit()

        # Best-effort overwrite the same SKILL.md file if path known.
        if sd.md_path:
            from pathlib import Path

            Path(sd.md_path).write_text(new_text.strip() + "\n", encoding="utf-8")

        if task_id:
            emit(task_id, f"skillAgent：迭代完成，已生成 v{new_sd.version}")

        return jsonify(
            {
                "ok": True,
                "version": new_sd.version,
                "content_md": new_sd.content_md,
                "md_path": new_sd.md_path,
            }
        )
    except Exception as e:  # noqa: BLE001
        log.exception("iterate_skill failed: %s", e)
        if task_id:
            emit(task_id, f"skillAgent：迭代失败：{e}", level="error")
        return jsonify({"error": str(e)}), 500


def _sse(event: str, data: dict, event_id: int | None = None) -> str:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    lines.append("")
    return "\n".join(lines) + "\n"

