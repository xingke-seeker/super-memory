"""Parse dsh (deepseek-harness) session storage into condensed transcripts.

Self-contained dsh harness adapter, same shape as the other parser_* modules.

Storage layout ($DSH_HOME or ~/.dsh):

  sessions/<project-key>/session-<id>/session.jsonl.zstd     (generation 0)
  sessions/<project-key>/session-<id>/session.vN.jsonl.zstd   (generation N >= 1)

Each session directory holds one zstd-compressed JSONL event log per format
generation. A migrated generation supersedes the full history of the versions
below it, so only the numerically highest generation file is read — mirroring
dsh's own `resolveGenerationInDirectory`. Uncompressed `.jsonl` files use the
same rule. Event types carrying the conversation (user/message with source kind
"user", assistant/message text blocks, tool/call, tool/result) are mapped to
turns; stream chunks and turn/step/request bookkeeping events are dropped.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

MAX_TOOL_CHARS = 500
MAX_MSG_CHARS = 2000
MAX_TRANSCRIPT_CHARS = 12000

DIGEST_PROMPT_PREFIX = "super-memory digest"

_GEN_RE = re.compile(r"^session(?:\.v([1-9][0-9]*))?\.jsonl(\.zstd)?$")


def default_dsh_home() -> Path:
    return Path(os.environ.get("DSH_HOME") or str(Path.home() / ".dsh"))


@dataclass
class Turn:
    role: str  # user | assistant | tool | tool_output
    text: str
    ts: str = ""


@dataclass
class Transcript:
    session_id: str
    cwd: str
    started_at: str
    source_file: str
    turns: list[Turn] = field(default_factory=list)

    def has_content(self) -> bool:
        return any(t.role in ("user", "assistant") for t in self.turns)


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"…[+{len(text) - limit} chars]"


def _iso(ms: int | float | None) -> str:
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000).isoformat(timespec="seconds")


def _zstd_decompress(data: bytes) -> bytes:
    """Decompress zstd bytes: stdlib compression.zstd, then zstandard, then zstd CLI."""
    try:
        from compression import zstd as _stdlib_zstd
        return _stdlib_zstd.decompress(data)
    except Exception:
        pass
    try:
        import zstandard
        return zstandard.ZstdDecompressor().decompress(data)
    except Exception:
        pass
    try:
        proc = subprocess.run(["zstd", "-dcq", "-"], input=data, capture_output=True, check=True)
        return proc.stdout
    except (OSError, subprocess.CalledProcessError) as e:
        raise OSError(f"no zstd decompressor available (compression.zstd / zstandard / zstd CLI): {e}")


def _current_generation(session_dir: Path) -> Path | None:
    """The numerically highest canonical generation file in one session directory."""
    best: tuple[int, Path] | None = None
    for entry in session_dir.iterdir():
        match = _GEN_RE.match(entry.name)
        if match is None or not entry.is_file():
            continue
        version = int(match.group(1) or 0)
        if best is None or version > best[0]:
            best = (version, entry)
    return best[1] if best else None


def _load_events(path: Path) -> list[dict]:
    raw = path.read_bytes()
    if path.name.endswith(".zstd"):
        raw = _zstd_decompress(raw)
    events = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def find_sessions(dsh_home: Path) -> list[Path]:
    """Session directories sorted by directory mtime."""
    sessions_dir = dsh_home / "sessions"
    if not sessions_dir.is_dir():
        return []
    dirs = [d for d in sessions_dir.glob("*/session-*") if d.is_dir()]
    return sorted(dirs, key=lambda d: d.stat().st_mtime)


def _tool_result_text(data: dict) -> str:
    parts = []
    for item in (data.get("message") or {}).get("content") or []:
        if item.get("type") != "tool-result":
            continue
        for chunk in item.get("content") or []:
            if isinstance(chunk, dict) and chunk.get("type") == "text" and chunk.get("text"):
                parts.append(chunk["text"])
    return "\n".join(parts)


def parse_session(session_dir: Path, cursor_ms: int = 0) -> tuple[Transcript | None, int]:
    """Parse one dsh session directory into a transcript.

    Returns (transcript, end_cursor). transcript is None when the session has
    not been updated past cursor_ms or is a super-memory digest worker session.
    The cursor is max(event time, generation file mtime) in milliseconds; the
    whole session is re-rendered on each change (wiki append dedupe makes
    re-distillation idempotent).
    """
    gen = _current_generation(session_dir)
    if gen is None:
        return None, cursor_ms
    events = _load_events(gen)
    if not events:
        return None, cursor_ms

    end_cursor = max(
        max(int(e.get("time") or 0) for e in events),
        int(gen.stat().st_mtime * 1000),
    )
    if end_cursor <= cursor_ms:
        return None, cursor_ms

    session_id = session_dir.name
    cwd = ""
    started_ms = 0
    for e in events:
        if e.get("type") == "session":
            session_id = e.get("id") or session_id
            cwd = e.get("cwd") or ""
            started_ms = e.get("createdAt") or 0
            break
    session_id = session_id.removeprefix("session-")

    turns: list[Turn] = []
    digest_session = False
    for e in events:
        etype = e.get("type")
        data = e.get("data") or {}
        ts = _iso(e.get("time"))
        if etype == "user/message":
            if (data.get("source") or {}).get("kind") != "user":
                continue  # skip injected agent-instructions / skill-catalog / plugin context
            for block in data.get("content") or []:
                text = block.get("text") if block.get("type") == "text" else ""
                if text and text.strip():
                    if not digest_session and text.startswith(DIGEST_PROMPT_PREFIX):
                        digest_session = True
                    turns.append(Turn(role="user", text=_clip(text, MAX_MSG_CHARS), ts=ts))
        elif etype == "assistant/message":
            for block in (data.get("message") or {}).get("content") or []:
                text = block.get("text") if block.get("type") == "text" else ""
                if text and text.strip():
                    turns.append(Turn(role="assistant", text=_clip(text, MAX_MSG_CHARS), ts=ts))
        elif etype == "tool/call":
            name = data.get("name") or "?"
            args = data.get("arguments") or ""
            turns.append(Turn(role="tool", text=f"{name}: {_clip(str(args), MAX_TOOL_CHARS)}", ts=ts))
        elif etype == "tool/result":
            out = _tool_result_text(data)
            if out:
                turns.append(Turn(role="tool_output", text=_clip(out, MAX_TOOL_CHARS), ts=ts))
        elif etype == "session/title":
            if str(data.get("title") or "").startswith(DIGEST_PROMPT_PREFIX):
                digest_session = True

    if digest_session:
        return None, end_cursor
    if not turns and not cwd:
        return None, end_cursor
    return (
        Transcript(
            session_id=session_id,
            cwd=cwd,
            started_at=_iso(started_ms),
            source_file=str(session_dir),
            turns=turns,
        ),
        end_cursor,
    )


def render_transcript(t: Transcript) -> str:
    """Render a condensed, token-bounded transcript for the distill prompt."""
    lines = [
        f"# Session {t.session_id}",
        f"# cwd: {t.cwd}",
        f"# started: {t.started_at}",
        "",
    ]
    role_label = {"user": "USER", "assistant": "ASSISTANT", "tool": "TOOL CALL", "tool_output": "TOOL OUT"}
    for turn in t.turns:
        label = role_label.get(turn.role, turn.role.upper())
        prefix = f"[{turn.ts}] " if turn.ts else ""
        lines.append(f"{prefix}{label}: {turn.text}")
        lines.append("")

    body = "\n".join(lines)
    if len(body) > MAX_TRANSCRIPT_CHARS:
        half = MAX_TRANSCRIPT_CHARS // 2
        body = (
            body[:half]
            + f"\n\n…[middle {len(body) - MAX_TRANSCRIPT_CHARS} chars omitted]…\n\n"
            + body[-half:]
        )
    return body
