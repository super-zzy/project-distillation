from __future__ import annotations

import os
import json
import time
from typing import Any, Dict, Optional

import requests


class AiRateLimitError(RuntimeError):
    def __init__(self, message: str, retry_after_s: Optional[int] = None):
        super().__init__(message)
        self.retry_after_s = retry_after_s


class AiHttpError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class AiClient:
    def __init__(self) -> None:
        base = os.getenv("AI_BASE_URL", "").rstrip("/")
        # tolerate misconfiguration: allow AI_BASE_URL ending with /v1
        if base.endswith("/v1"):
            base = base[: -len("/v1")]
        self.base_url = base
        self.model = os.getenv("AI_MODEL", "zai-org/GLM-4.7")
        raw_key = os.getenv("AI_API_KEY", "") or ""
        # tolerate either "sk-xxx" or "Bearer sk-xxx"
        self.api_key = raw_key.strip().removeprefix("Bearer ").strip()
        self.api_mode = os.getenv("AI_API_MODE", "AI")
        self.org_sender_id = os.getenv("AI_ORG_SENDER_ID", "")
        self.temperature = float(os.getenv("AI_TEMPERATURE", "0.1"))

    def chat(
        self,
        system: str,
        user: str,
        timeout_s: int = 120,
        *,
        meta: Optional[dict] = None,
    ) -> str:
        if not self.base_url:
            raise RuntimeError("AI_BASE_URL not set")
        if not self.api_key:
            raise RuntimeError("AI_API_KEY not set")

        url = f"{self.base_url}/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "X-API-Mode": self.api_mode,
        }
        if self.org_sender_id:
            headers["X-OrgSender-ID"] = self.org_sender_id

        payload: Dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }

        start = time.time()
        last_err: Optional[Exception] = None
        max_attempts = int(os.getenv("AI_MAX_ATTEMPTS", "8"))
        base_backoff = float(os.getenv("AI_BACKOFF_BASE_S", "1.5"))
        max_backoff = float(os.getenv("AI_BACKOFF_MAX_S", "30"))

        for i in range(max_attempts):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=timeout_s,
                    allow_redirects=True,
                )
                if resp.status_code == 429:
                    ra = resp.headers.get("Retry-After")
                    retry_after_s = int(ra) if ra and ra.isdigit() else None
                    raise AiRateLimitError(
                        f"429 Too Many Requests for url: {url}",
                        retry_after_s=retry_after_s,
                    )
                if 500 <= resp.status_code <= 599:
                    raise AiHttpError(resp.status_code, f"{resp.status_code} Server Error for url: {url}")
                if resp.status_code >= 400:
                    raise AiHttpError(resp.status_code, f"{resp.status_code} Client Error for url: {url}")
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                _record_ai_call(
                    ok=True,
                    meta=meta,
                    model=self.model,
                    request_payload=payload,
                    response_text=content,
                    duration_ms=int((time.time() - start) * 1000),
                    error=None,
                )
                return content
            except Exception as e:  # noqa: BLE001
                last_err = e
                # Retry only for rate limit / transient server/network issues.
                should_retry = isinstance(e, AiRateLimitError) or isinstance(e, AiHttpError) and getattr(e, "status_code", 0) >= 500
                should_retry = should_retry or isinstance(e, requests.exceptions.RequestException)

                if not should_retry or i == max_attempts - 1:
                    break

                if isinstance(e, AiRateLimitError) and e.retry_after_s is not None:
                    sleep_s = min(max_backoff, max(1.0, float(e.retry_after_s)))
                else:
                    sleep_s = min(max_backoff, base_backoff * (i + 1))
                time.sleep(sleep_s)
        _record_ai_call(
            ok=False,
            meta=meta,
            model=self.model,
            request_payload=payload,
            response_text=None,
            duration_ms=int((time.time() - start) * 1000),
            error=str(last_err),
        )
        raise RuntimeError(f"AI request failed: {last_err}")


def _record_ai_call(
    *,
    ok: bool,
    meta: Optional[dict],
    model: str,
    request_payload: dict,
    response_text: Optional[str],
    duration_ms: int,
    error: Optional[str],
) -> None:
    """
    Best-effort DB record. No-op if DB/app context not available.
    """
    if meta is None:
        return
    try:
        from .db import db
        from .models import AiCall

        call = AiCall(
            task_id=meta.get("task_id"),
            project_id=meta.get("project_id"),
            agent=meta.get("agent", "other"),
            model=model,
            branch_name=meta.get("branch_name"),
            commit_sha=meta.get("commit_sha"),
            prompt_id=meta.get("prompt_id"),
            # Keep request_json STRICTLY as the payload we send to AI.
            request_json=json.dumps(request_payload, ensure_ascii=False),
            response_text=response_text,
            status="ok" if ok else "error",
            error=error,
            duration_ms=duration_ms,
        )
        db.session.add(call)
        db.session.commit()
    except Exception:
        try:
            db.session.rollback()  # type: ignore[name-defined]
        except Exception:
            pass

