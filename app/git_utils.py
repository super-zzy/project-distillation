from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, List, Tuple

from git import Repo


def open_repo(project_path: str) -> Repo:
    return Repo(project_path)


def list_branches(repo: Repo) -> List[str]:
    branches = []
    for b in repo.branches:
        branches.append(b.name)
    branches.sort()
    return branches


def iter_commits_for_branch(repo: Repo, branch_name: str) -> Iterable[Tuple[str, datetime]]:
    commits = list(repo.iter_commits(branch_name))
    commits.sort(key=lambda c: c.committed_datetime)
    for c in commits:
        yield (c.hexsha, c.committed_datetime)


def commit_metadata(repo: Repo, commit_sha: str) -> dict:
    c = repo.commit(commit_sha)
    subject = c.message.splitlines()[0] if c.message else ""
    author = str(c.author) if c.author else ""
    return {
        "sha": c.hexsha,
        "commit_time": c.committed_datetime,
        "author": author,
        "subject": subject,
    }


def commit_payload_for_ai(repo: Repo, commit_sha: str, max_chars: int = 14000) -> str:
    # Include patch but keep bounded to avoid huge prompts.
    text = repo.git.show(
        commit_sha,
        "--no-color",
        "--stat",
        "--patch",
        "--max-count=1",
    )
    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[TRUNCATED]\n"
    return text


def safe_slug(s: str) -> str:
    s = s.strip().replace(" ", "_")
    s = re.sub(r"[^0-9A-Za-z_\-\.]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s[:120] if len(s) > 120 else s

