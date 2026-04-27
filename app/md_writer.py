from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from .git_utils import safe_slug


def project_root(output_root: str, project_name: str) -> Path:
    return Path(output_root).resolve() / safe_slug(project_name)


def ensure_project_structure(root: Path) -> None:
    (root / "00_索引与模板" / "templates").mkdir(parents=True, exist_ok=True)
    (root / "01_commit").mkdir(parents=True, exist_ok=True)
    (root / "02_branch").mkdir(parents=True, exist_ok=True)
    (root / "03_summary").mkdir(parents=True, exist_ok=True)
    (root / "04_skill").mkdir(parents=True, exist_ok=True)

    readme = root / "00_索引与模板" / "README.md"
    if not readme.exists():
        readme.write_text(
            "# 项目知识库\n\n- `01_commit/`：按 commit 维度\n- `02_branch/`：按 branch 汇总\n- `03_summary/`：全项目总结\n",
            encoding="utf-8",
        )
    index = root / "00_索引与模板" / "index.md"
    if not index.exists():
        index.write_text("# Index\n\n", encoding="utf-8")


def commit_md_path(root: Path, branch_name: str, commit_sha: str, commit_time: datetime) -> Path:
    ts = commit_time.strftime("%Y%m%d_%H%M%S")
    name = f"{safe_slug(branch_name)}_{commit_sha[:10]}_{ts}.md"
    return root / "01_commit" / name


def branch_md_path(root: Path, branch_name: str) -> Path:
    return root / "02_branch" / f"{safe_slug(branch_name)}.md"


def summary_md_path(root: Path) -> Path:
    return root / "03_summary" / "summary.md"

def skill_md_path(root: Path) -> Path:
    return root / "04_skill" / "SKILL.md"


def write_commit_md(path: Path, header_one_liner: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Commit 总结\n\n**一句话**：{header_one_liner}\n\n## 详细分析\n\n{body}\n",
        encoding="utf-8",
    )


def write_branch_md(path: Path, header_one_liner: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Branch 总结\n\n**一句话**：{header_one_liner}\n\n## 详细分析\n\n{body}\n",
        encoding="utf-8",
    )


def write_summary_md(path: Path, *, one_liner: str, detail_md: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# 项目总结\n\n**一句话**：{one_liner}\n\n{detail_md.strip()}\n",
        encoding="utf-8",
    )


def write_skill_md(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")

