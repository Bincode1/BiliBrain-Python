from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from bilibrain.tools.contracts import ToolCallResult, ToolCallTimer
from bilibrain.tools.runtime.contracts import BaseToolRuntime, RuntimeExecResult


DEFAULT_TIMEOUT_SECONDS = 45
DEFAULT_MAX_CHARS = 20000
MAX_ALLOWED_CHARS = 50000


def _normalize_url(raw_url: str) -> str:
    value = str(raw_url or "").strip()
    if not value:
        raise RuntimeError("Page URL cannot be empty.")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeError("Page URL must be a valid http or https URL.")
    return value


def _normalize_text(value: str, *, max_chars: int) -> str:
    normalized = str(value or "").replace("\r\n", "\n").strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip() + "\n...[truncated]"


def _build_session_name(workspace_id: str, trace_id: str) -> str:
    raw = f"browser-{workspace_id}-{trace_id[:8]}"
    normalized = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in raw)
    return normalized[:64] or "browser-session"


def _build_command(
    *,
    session_name: str,
    max_output_chars: int,
    command_parts: list[str],
    allowed_domain: str | None = None,
) -> str:
    parts = [
        "npx",
        "agent-browser",
        "--session",
        session_name,
        "--max-output",
        str(max_output_chars),
    ]
    if allowed_domain:
        parts.extend(["--allowed-domains", allowed_domain])
    parts.extend(command_parts)
    return subprocess.list2cmdline(parts)


async def _exec_browser_command(
    runtime: BaseToolRuntime,
    *,
    workspace_root: Path,
    session_name: str,
    max_output_chars: int,
    command_parts: list[str],
    timeout_seconds: int,
    allowed_domain: str | None = None,
) -> RuntimeExecResult:
    command = _build_command(
        session_name=session_name,
        max_output_chars=max_output_chars,
        command_parts=command_parts,
        allowed_domain=allowed_domain,
    )
    return await runtime.exec(
        workspace_root=workspace_root,
        command=command,
        cwd=".",
        timeout_seconds=timeout_seconds,
    )


def _raise_command_failure(step: str, result: RuntimeExecResult) -> None:
    stderr = str(result.stderr or "").strip()
    stdout = str(result.stdout or "").strip()
    detail = stderr or stdout or f"exit_code={result.exit_code}"
    raise RuntimeError(
        f"agent-browser failed during {step}. "
        f"Ensure the CLI is available and run `npx agent-browser install` once if the browser is missing. "
        f"Detail: {detail}"
    )


async def browser_read_page_tool(
    *,
    runtime: BaseToolRuntime,
    workspace_root: Path,
    arguments: dict[str, Any],
    workspace_id: str = "_local",
    trace_id: str = "local-browser-read",
) -> ToolCallResult:
    timer = ToolCallTimer()
    url = _normalize_url(str(arguments.get("url") or ""))
    selector = str(arguments.get("selector") or "body").strip() or "body"
    timeout_seconds = max(int(arguments.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS), 1)
    max_chars = min(max(int(arguments.get("max_chars") or DEFAULT_MAX_CHARS), 1), MAX_ALLOWED_CHARS)
    parsed = urlparse(url)
    allowed_domain = parsed.netloc
    session_name = _build_session_name(workspace_id, trace_id)

    try:
        open_result = await _exec_browser_command(
            runtime,
            workspace_root=workspace_root,
            session_name=session_name,
            max_output_chars=max_chars,
            command_parts=["open", url],
            timeout_seconds=timeout_seconds,
            allowed_domain=allowed_domain,
        )
        if open_result.exit_code != 0 or open_result.timed_out:
            _raise_command_failure("open", open_result)

        wait_result = await _exec_browser_command(
            runtime,
            workspace_root=workspace_root,
            session_name=session_name,
            max_output_chars=max_chars,
            command_parts=["wait", "--load", "networkidle"],
            timeout_seconds=timeout_seconds,
            allowed_domain=allowed_domain,
        )
        if wait_result.exit_code != 0 or wait_result.timed_out:
            _raise_command_failure("wait", wait_result)

        title_result = await _exec_browser_command(
            runtime,
            workspace_root=workspace_root,
            session_name=session_name,
            max_output_chars=max_chars,
            command_parts=["get", "title"],
            timeout_seconds=timeout_seconds,
            allowed_domain=allowed_domain,
        )
        if title_result.exit_code != 0 or title_result.timed_out:
            _raise_command_failure("get title", title_result)

        final_url_result = await _exec_browser_command(
            runtime,
            workspace_root=workspace_root,
            session_name=session_name,
            max_output_chars=max_chars,
            command_parts=["get", "url"],
            timeout_seconds=timeout_seconds,
            allowed_domain=allowed_domain,
        )
        if final_url_result.exit_code != 0 or final_url_result.timed_out:
            _raise_command_failure("get url", final_url_result)

        text_result = await _exec_browser_command(
            runtime,
            workspace_root=workspace_root,
            session_name=session_name,
            max_output_chars=max_chars,
            command_parts=["get", "text", selector],
            timeout_seconds=timeout_seconds,
            allowed_domain=allowed_domain,
        )
        if text_result.exit_code != 0 or text_result.timed_out:
            _raise_command_failure("get text", text_result)

        title = _normalize_text(title_result.stdout, max_chars=max_chars)
        final_url = _normalize_text(final_url_result.stdout, max_chars=max_chars)
        text = _normalize_text(text_result.stdout, max_chars=max_chars)
    finally:
        try:
            await _exec_browser_command(
                runtime,
                workspace_root=workspace_root,
                session_name=session_name,
                max_output_chars=max_chars,
                command_parts=["close"],
                timeout_seconds=min(timeout_seconds, 15),
                allowed_domain=allowed_domain,
            )
        except Exception:
            pass

    return ToolCallResult(
        ok=True,
        tool_name="browser_read_page",
        workspace_id=workspace_id,
        trace_id=trace_id,
        payload={
            "url": url,
            "final_url": final_url,
            "title": title,
            "text": text,
            "text_length": len(text),
            "selector": selector,
            "session_name": session_name,
            "provider": "agent_browser",
        },
        duration_ms=timer.elapsed_ms(),
    )
