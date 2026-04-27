from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Optional

from flask import Flask
from sqlalchemy import and_

from .ai_client import AiClient
from .db import db
from .git_utils import commit_metadata, commit_payload_for_ai, iter_commits_for_branch, list_branches, open_repo
from .md_writer import (
    branch_md_path,
    commit_md_path,
    ensure_project_structure,
    project_root,
    skill_md_path,
    summary_md_path,
    write_branch_md,
    write_commit_md,
    write_skill_md,
    write_summary_md,
)
from .models import Branch, Commit, Project, SkillDraft, Task, TaskEvent
from .utils import get_logger


_worker_lock = threading.Lock()
_worker_started = False
log = get_logger("worker")
_worker_app: Optional[Flask] = None
_task_runners_lock = threading.Lock()
_task_runners: dict[str, threading.Thread] = {}


def _ai_chat_with_heartbeat(*, task: Task, every_s: float = 5.0, label: str, call):
    """
    Run a blocking AI call but keep emitting heartbeat events so UI shows progress.
    """
    stop = threading.Event()

    def beat():
        start = time.time()
        while not stop.wait(every_s):
            waited = int(time.time() - start)
            # Heartbeat runs in a separate thread; db.session requires app context.
            if _worker_app is None:
                continue
            with _worker_app.app_context():
                emit(task.id, f"{label}（等待AI响应中 {waited}s）")

    t = threading.Thread(target=beat, daemon=True)
    t.start()
    try:
        emit(task.id, f"{label}（请求已发送，等待响应）")
        return call()
    finally:
        stop.set()


def ensure_worker_started(app: Flask) -> None:
    if (os.getenv("DISABLE_WORKER") or "").strip() in ("1", "true", "True", "yes", "Y"):
        log.warning("worker disabled by DISABLE_WORKER=%s", os.getenv("DISABLE_WORKER"))
        return
    global _worker_app
    _worker_app = app
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, args=(app,), daemon=True)
        t.start()
        _worker_started = True
        log.info("worker started")


def ensure_task_runner(app: Flask, task_id: str) -> None:
    """
    Start a dedicated background runner for a specific task.

    This is a safety net in case the global worker loop cannot pick up tasks
    (e.g. environment/threading quirks). It is idempotent per task_id.
    """
    with _task_runners_lock:
        t = _task_runners.get(task_id)
        if t and t.is_alive():
            return
        nt = threading.Thread(target=_run_task_until_done, args=(app, task_id), daemon=True)
        _task_runners[task_id] = nt
        nt.start()


def _run_task_until_done(app: Flask, task_id: str) -> None:
    with app.app_context():
        log.info("task runner started task=%s", task_id)
        while True:
            task = Task.query.get(task_id)
            if not task:
                log.warning("task runner exit: task not found task=%s", task_id)
                return

            if task.status in ("completed", "failed", "stopped"):
                log.info("task runner exit: status=%s task=%s", task.status, task_id)
                return

            if task.status == "queued":
                _set_task(task, status="running", message="任务开始", phase="main")
                emit(task.id, "任务开始")

            if task.status == "paused":
                time.sleep(0.8)
                continue

            try:
                if task.phase == "main":
                    _run_main_agent(task)
                elif task.phase == "commit":
                    _run_commit_agents(task)
                elif task.phase == "branch":
                    _run_branch_agents(task)
                elif task.phase == "summary":
                    _run_summary_agent(task)
                else:
                    _set_task(task, status="failed", error=f"Unknown phase: {task.phase}")
                    emit(task.id, f"Unknown phase: {task.phase}", level="error")
                    return
            except Exception as e:  # noqa: BLE001
                try:
                    db.session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                _set_task(task, status="failed", error=str(e))
                emit(task.id, f"任务失败：{e}", level="error")
                log.exception("task runner failed task=%s err=%s", task_id, e)
                return

            # Yield to avoid tight looping; phase handlers are already paced.
            time.sleep(0.2)

def new_task_id() -> str:
    return uuid.uuid4().hex


def emit(task_id: str, message: str, level: str = "info", data: Optional[dict] = None) -> None:
    evt = TaskEvent(
        task_id=task_id,
        level=level,
        message=message,
        data_json=json.dumps(data, ensure_ascii=False) if data is not None else None,
    )
    db.session.add(evt)
    db.session.commit()
    if level == "error":
        log.error("task=%s %s data=%s", task_id, message, data)
    elif level == "warn":
        log.warning("task=%s %s data=%s", task_id, message, data)
    else:
        log.info("task=%s %s data=%s", task_id, message, data)


def _set_task(
    task: Task,
    *,
    status: Optional[str] = None,
    phase: Optional[str] = None,
    message: Optional[str] = None,
    progress_current: Optional[int] = None,
    progress_total: Optional[int] = None,
    cursor_branch: Optional[str] = None,
    cursor_commit: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    if status is not None:
        task.status = status
    if phase is not None:
        task.phase = phase
    if message is not None:
        task.message = message
    if progress_current is not None:
        task.progress_current = progress_current
    if progress_total is not None:
        task.progress_total = progress_total
    if cursor_branch is not None:
        task.cursor_branch = cursor_branch
    if cursor_commit is not None:
        task.cursor_commit = cursor_commit
    if error is not None:
        task.error = error
    db.session.add(task)
    db.session.commit()


def _worker_loop(app: Flask) -> None:
    with app.app_context():
        log.info("worker loop entered")
        while True:
            try:
                _tick_once()
            except Exception as e:  # noqa: BLE001
                # last resort: avoid thread death
                try:
                    db.session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                log.exception("worker loop error: %s", e)
                time.sleep(1.5)
                _ = e
            time.sleep(0.5)


def _tick_once() -> None:
    task: Optional[Task] = (
        Task.query.filter(Task.status.in_(("queued", "running")))
        .order_by(Task.updated_at.asc(), Task.created_at.asc())
        .first()
    )
    if not task:
        return

    if task.status == "queued":
        _set_task(task, status="running", message="任务开始", phase="main")
        emit(task.id, "任务开始")

    if task.status == "paused":
        return
    if task.status == "stopped":
        return

    if task.phase == "main":
        _run_main_agent(task)
    elif task.phase == "commit":
        _run_commit_agents(task)
    elif task.phase == "branch":
        _run_branch_agents(task)
    elif task.phase == "summary":
        _run_summary_agent(task)
    else:
        _set_task(task, status="failed", error=f"Unknown phase: {task.phase}")
        emit(task.id, f"Unknown phase: {task.phase}", level="error")


def _run_main_agent(task: Task) -> None:
    project = Project.query.get(task.project_id)
    if not project:
        _set_task(task, status="failed", error="Project not found")
        emit(task.id, "Project not found", level="error")
        return

    output_root = project_root(project.output_root, project.name)
    ensure_project_structure(output_root)

    emit(task.id, "遍历 branch/commit，生成全量 commit 清单")
    _set_task(task, message="遍历 branch/commit")
    log.info("mainAgent start task=%s project=%s", task.id, project.name)

    repo = open_repo(project.local_path)
    branches = list_branches(repo)
    if not branches:
        _set_task(task, status="failed", error="No branches found")
        emit(task.id, "No branches found", level="error")
        return

    total_commits = 0
    for b in branches:
        for sha, ctime in iter_commits_for_branch(repo, b):
            meta = commit_metadata(repo, sha)
            existing = Commit.query.filter_by(project_id=project.id, branch_name=b, commit_sha=sha).first()
            if existing:
                continue
            db.session.add(
                Commit(
                    project_id=project.id,
                    branch_name=b,
                    commit_sha=sha,
                    commit_time=meta["commit_time"],
                    author=meta["author"],
                    subject=meta["subject"],
                    status="queued",
                )
            )
            total_commits += 1
        db.session.commit()

    # Ensure branch rows exist (queued)
    for b in branches:
        br = Branch.query.filter_by(project_id=project.id, name=b).first()
        if not br:
            db.session.add(Branch(project_id=project.id, name=b, status="queued"))
    db.session.commit()

    # Move to commit phase
    commit_total = Commit.query.filter_by(project_id=project.id).count()
    _set_task(task, phase="commit", message="开始分析 commit", progress_current=0, progress_total=commit_total)
    emit(task.id, f"commit 总数：{commit_total}，开始逐个分析")
    log.info("mainAgent queued commits=%s task=%s", commit_total, task.id)


def _run_commit_agents(task: Task) -> None:
    project = Project.query.get(task.project_id)
    if not project:
        _set_task(task, status="failed", error="Project not found")
        emit(task.id, "Project not found", level="error")
        return

    if task.status == "paused":
        return

    output_root = project_root(project.output_root, project.name)
    ensure_project_structure(output_root)

    done = Commit.query.filter_by(project_id=project.id, status="completed").count()
    total = Commit.query.filter_by(project_id=project.id).count()
    _set_task(task, progress_current=done, progress_total=total, message="分析 commit 中")

    next_commit: Optional[Commit] = (
        Commit.query.filter_by(project_id=project.id, status="queued")
        .order_by(Commit.commit_time.asc())
        .first()
    )
    if not next_commit:
        # all commits handled (completed/failed)
        emit(task.id, "commit 分析完成，进入 branch 汇总")
        _set_task(task, phase="branch", message="开始分析 branch", progress_current=0, progress_total=0)
        log.info("commitAgent done task=%s", task.id)
        return

    # lock the commit row (best-effort)
    next_commit.status = "running"
    db.session.add(next_commit)
    db.session.commit()

    emit(task.id, f"commitAgent：分析 {next_commit.branch_name} {next_commit.commit_sha[:10]}")
    emit(task.id, "commitAgent：调用 AI 分析本次提交", data={"branch": next_commit.branch_name, "sha": next_commit.commit_sha[:10]})
    log.info(
        "commitAgent start task=%s branch=%s sha=%s",
        task.id,
        next_commit.branch_name,
        next_commit.commit_sha,
    )

    try:
        repo = open_repo(project.local_path)
        patch = commit_payload_for_ai(repo, next_commit.commit_sha)
        system = "你是一个资深软件架构与代码审查助手，擅长从提交中提炼设计意图。输出要简洁、结构化。"
        user = (
            "请分析下面这个 Git commit（包含 diff/stat）。\n\n"
            "要求：\n"
            "1) 先给出【一句话总结】（20~40字，描述这次提交的核心意图/设计动机）\n"
            "2) 再给出【详细分析】（要点式即可：改动范围、为何这样设计、可能影响、潜在风险）\n\n"
            f"=== COMMIT SHA: {next_commit.commit_sha}\n"
            f"=== BRANCH: {next_commit.branch_name}\n"
            f"=== COMMIT TIME: {next_commit.commit_time.isoformat()}\n\n"
            f"{patch}"
        )

        ai = AiClient()
        resp = _ai_chat_with_heartbeat(
            task=task,
            label="commitAgent：AI分析提交",
            call=lambda: ai.chat(
                system=system,
                user=user,
                meta={
                    "task_id": task.id,
                    "project_id": project.id,
                    "agent": "commit",
                    "branch_name": next_commit.branch_name,
                    "commit_sha": next_commit.commit_sha,
                    "prompt_id": "Prompt/commit_analysis.v1.json",
                },
            ),
        )
        one_liner, detail = _split_one_liner(resp)

        mdp = commit_md_path(output_root, next_commit.branch_name, next_commit.commit_sha, next_commit.commit_time)
        write_commit_md(mdp, header_one_liner=one_liner, body=detail)

        next_commit.one_liner = one_liner
        next_commit.ai_analysis = resp
        next_commit.md_path = str(mdp)
        next_commit.status = "completed"
        db.session.add(next_commit)
        db.session.commit()

        emit(task.id, f"commit 已完成：{next_commit.commit_sha[:10]} — {one_liner}")
        log.info("commitAgent completed task=%s sha=%s", task.id, next_commit.commit_sha)
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        next_commit.status = "failed"
        next_commit.error = str(e)
        db.session.add(next_commit)
        db.session.commit()
        emit(task.id, f"commit 分析失败：{next_commit.commit_sha[:10]} {e}", level="error")
        log.exception("commitAgent failed task=%s sha=%s err=%s", task.id, next_commit.commit_sha, e)


def _run_branch_agents(task: Task) -> None:
    project = Project.query.get(task.project_id)
    if not project:
        _set_task(task, status="failed", error="Project not found")
        emit(task.id, "Project not found", level="error")
        return

    output_root = project_root(project.output_root, project.name)
    ensure_project_structure(output_root)

    total = Branch.query.filter_by(project_id=project.id).count()
    done = Branch.query.filter_by(project_id=project.id, status="completed").count()
    _set_task(task, progress_current=done, progress_total=total, message="分析 branch 中")

    next_branch: Optional[Branch] = (
        Branch.query.filter_by(project_id=project.id, status="queued")
        .order_by(Branch.name.asc())
        .first()
    )
    if not next_branch:
        emit(task.id, "branch 汇总完成，进入全项目总结")
        _set_task(task, phase="summary", message="开始生成 summary", progress_current=0, progress_total=1)
        log.info("branchAgent done task=%s", task.id)
        return

    next_branch.status = "running"
    db.session.add(next_branch)
    db.session.commit()

    emit(task.id, f"branchAgent：汇总 {next_branch.name}")
    emit(task.id, "branchAgent：调用 AI 汇总分支演进", data={"branch": next_branch.name})
    log.info("branchAgent start task=%s branch=%s", task.id, next_branch.name)

    try:
        commits = (
            Commit.query.filter(
                and_(
                    Commit.project_id == project.id,
                    Commit.branch_name == next_branch.name,
                    Commit.status == "completed",
                )
            )
            .order_by(Commit.commit_time.asc())
            .all()
        )
        lines = []
        for c in commits:
            if c.one_liner:
                lines.append(f"- {c.commit_time.strftime('%Y-%m-%d %H:%M:%S')} {c.commit_sha[:10]} {c.one_liner}")
            else:
                lines.append(f"- {c.commit_time.strftime('%Y-%m-%d %H:%M:%S')} {c.commit_sha[:10]} (no summary)")

        system = "你是一个资深软件架构分析助手，擅长从提交序列中抽象分支目标与里程碑。输出要简洁、结构化。"
        user = (
            f"下面是分支 `{next_branch.name}` 的提交一句话摘要（按时间顺序）。\n\n"
            "要求：\n"
            "1) 先给出【一句话总结】（20~40字，概括该分支的总体目标/主题）\n"
            "2) 再给出【详细分析】（分阶段/里程碑、关键设计决策、重要变更点）\n\n"
            "提交列表：\n"
            + "\n".join(lines)
        )

        ai = AiClient()
        resp = _ai_chat_with_heartbeat(
            task=task,
            label="branchAgent：AI汇总分支",
            call=lambda: ai.chat(
                system=system,
                user=user,
                meta={
                    "task_id": task.id,
                    "project_id": project.id,
                    "agent": "branch",
                    "branch_name": next_branch.name,
                    "prompt_id": "Prompt/branch_analysis.v1.json",
                },
            ),
        )
        one_liner, detail = _split_one_liner(resp)

        mdp = branch_md_path(output_root, next_branch.name)
        write_branch_md(mdp, header_one_liner=one_liner, body=detail)

        next_branch.one_liner = one_liner
        next_branch.ai_analysis = resp
        next_branch.md_path = str(mdp)
        next_branch.status = "completed"
        db.session.add(next_branch)
        db.session.commit()

        emit(task.id, f"branch 已完成：{next_branch.name} — {one_liner}")
        log.info("branchAgent completed task=%s branch=%s", task.id, next_branch.name)
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        next_branch.status = "failed"
        next_branch.error = str(e)
        db.session.add(next_branch)
        db.session.commit()
        emit(task.id, f"branch 分析失败：{next_branch.name} {e}", level="error")
        log.exception("branchAgent failed task=%s branch=%s err=%s", task.id, next_branch.name, e)


def _run_summary_agent(task: Task) -> None:
    project = Project.query.get(task.project_id)
    if not project:
        _set_task(task, status="failed", error="Project not found")
        emit(task.id, "Project not found", level="error")
        return

    output_root = project_root(project.output_root, project.name)
    ensure_project_structure(output_root)

    emit(task.id, "summaryAgent：生成全项目总结")
    emit(task.id, "summaryAgent：调用 AI 生成全项目总结")
    _set_task(task, message="生成 summary", progress_current=0, progress_total=1)
    log.info("summaryAgent start task=%s", task.id)

    try:
        branches = Branch.query.filter_by(project_id=project.id, status="completed").order_by(Branch.name.asc()).all()
        lines = []
        for b in branches:
            if b.one_liner:
                lines.append(f"- {b.name}: {b.one_liner}")
            else:
                lines.append(f"- {b.name}: (no summary)")

        prompt = _load_prompt_json("Prompt/project_summary.v1.json")
        system = str(prompt.get("system_prompt") or "")
        user = _render_template(
            str(prompt.get("user_template") or ""),
            {
                "project_name": project.name,
                "branch_one_liners": "\n".join(lines),
            },
        )

        ai = AiClient()
        resp = _ai_chat_with_heartbeat(
            task=task,
            label="summaryAgent：AI生成总结",
            call=lambda: ai.chat(
                system=system,
                user=user,
                meta={
                    "task_id": task.id,
                    "project_id": project.id,
                    "agent": "summary",
                    "prompt_id": "Prompt/project_summary.v1.json",
                },
            ),
        )

        out = _parse_strict_json(resp)
        one_liner = str(out.get("one_liner") or "（无）").strip()[:120] or "（无）"
        detail_md = str(out.get("detail_md") or "").strip() or "（无）"

        mdp = summary_md_path(output_root)
        write_summary_md(mdp, one_liner=one_liner, detail_md=detail_md)

        # Generate an initial Cursor Skill draft (SKILL.md) and persist it for iteration.
        emit(task.id, "summaryAgent：生成 Cursor Skill 初稿（SKILL.md）")
        skill_prompt = _load_prompt_json("Prompt/skill_distill.v1.json")
        skill_system = str(skill_prompt.get("system_prompt") or "")
        skill_user = _render_template(
            str(skill_prompt.get("user_template") or ""),
            {
                "project_name": project.name,
                "project_one_liner": one_liner,
                "project_detail_md": detail_md,
                "branch_one_liners": "\n".join(lines),
            },
        )
        skill_text = _ai_chat_with_heartbeat(
            task=task,
            label="skillAgent：AI生成 SKILL.md",
            call=lambda: ai.chat(
                system=skill_system,
                user=skill_user,
                meta={
                    "task_id": task.id,
                    "project_id": project.id,
                    "agent": "skill",
                    "prompt_id": "Prompt/skill_distill.v1.json",
                },
            ),
        )
        skill_path = skill_md_path(output_root)
        write_skill_md(skill_path, skill_text)

        version = (db.session.query(db.func.max(SkillDraft.version)).filter(SkillDraft.project_id == project.id).scalar() or 0) + 1
        sd = SkillDraft(
            task_id=task.id,
            project_id=project.id,
            version=int(version),
            content_md=skill_text,
            md_path=str(skill_path),
        )
        db.session.add(sd)
        db.session.commit()
        emit(task.id, f"Skill 初稿已生成：v{sd.version}（{skill_path}）")

        _set_task(task, status="completed", message="完成", progress_current=1, progress_total=1)
        emit(task.id, "任务完成")
        log.info("summaryAgent completed task=%s", task.id)
    except Exception as e:  # noqa: BLE001
        db.session.rollback()
        _set_task(task, status="failed", error=str(e))
        emit(task.id, f"summary 失败：{e}", level="error")
        log.exception("summaryAgent failed task=%s err=%s", task.id, e)


def _load_prompt_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _render_template(tpl: str, vars: dict) -> str:
    # Minimal moustache-like renderer for Prompt/*.json templates.
    out = tpl
    for k, v in vars.items():
        out = out.replace("{{" + str(k) + "}}", str(v))
    return out


def _parse_strict_json(text: str) -> dict:
    """
    Parse model output that SHOULD be strict JSON.
    Best-effort: if it contains extra text, try to extract the first top-level JSON object.
    """
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        pass
    # Extract first {...} block.
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except Exception:
            return {}
    return {}


def _split_one_liner(ai_text: str) -> tuple[str, str]:
    """
    Best-effort extract one-liner + detail from model output.
    """
    text = (ai_text or "").strip()
    if not text:
        return ("（无）", "（无）")

    # Common patterns: "一句话总结：" / "【一句话总结】"
    for key in ("一句话总结", "【一句话总结】", "一、", "1)"):
        if key in text:
            break

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ("（无）", "（无）")

    first = lines[0]
    first = first.replace("【一句话总结】", "").replace("一句话总结", "").replace("：", "").strip()
    if len(first) < 6 and len(lines) > 1:
        first = lines[1]

    detail = "\n".join(lines[1:]) if len(lines) > 1 else text
    return (first[:120], detail)

