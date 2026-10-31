"""Parse Trae session memory jsonl summaries into condensed session transcripts.

Trae（含 Trae CN）把原始对话存在云端，本地只落一份按 message 增量追加的
会话摘要（intent/actions/outcome/learned）。本解析器消费这份摘要：
目录结构 ~/.trae-cn/memory/projects/<项目slug>/<YYYYMMDD>/session_memory_<id>.jsonl
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

MAX_MSG_CHARS = 2000
MAX_TRANSCRIPT_CHARS = 12000


def default_trae_home() -> Path:
    env = os.environ.get("TRAE_HOME")
    if env:
        return Path(env)
    for candidate in (Path.home() / ".trae-cn", Path.home() / ".trae"):
        if candidate.is_dir():
            return candidate
    return Path.home() / ".trae-cn"


def default_projects_dir() -> Path:
    return default_trae_home() / "memory" / "projects"


@dataclass
class Turn:
    role: str  # user | assistant | tool
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


def _bullets(items) -> str:
    return "\n".join(f"- {str(i).strip()}" for i in items if str(i).strip())


def find_log_files(trae_home: Path) -> list[Path]:
    projects_dir = trae_home / "memory" / "projects"
    if not projects_dir.is_dir():
        return []
    return sorted(projects_dir.glob("*/*/session_memory_*.jsonl"))


def _session_id_of(path: Path) -> str:
    stem = path.stem
    return stem[len("session_memory_"):] if stem.startswith("session_memory_") else stem


def _project_slug(path: Path) -> str:
    # <trae-home>/memory/projects/<slug>/<YYYYMMDD>/session_memory_<id>.jsonl
    return path.parent.parent.name


def _date_of_dir(path: Path) -> str:
    d = path.parent.name
    if len(d) == 8 and d.isdigit():
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return ""


def parse_file(path: Path, offset: int = 0) -> tuple[Transcript | None, int]:
    """Parse complete new JSONL records, retaining an incomplete trailing line."""
    size = path.stat().st_size
    if offset >= size:
        return None, offset

    with open(path, "rb") as fh:
        fh.seek(offset)
        chunk = fh.read()
    if not chunk.endswith(b"\n"):
        last_newline = chunk.rfind(b"\n")
        if last_newline < 0:
            return None, offset
        chunk = chunk[:last_newline + 1]
    end_offset = offset + len(chunk)

    session_id = _session_id_of(path)
    cwd = _project_slug(path)
    started_at = _date_of_dir(path)
    turns: list[Turn] = []

    for raw in chunk.decode("utf-8", errors="replace").splitlines():
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue

        ts = str(rec.get("message_summary_time") or "")[:19]
        intent = str(rec.get("intent") or "").strip()
        actions = rec.get("actions") or []
        outcome = str(rec.get("outcome") or "").strip()
        learned = rec.get("learned") or []
        if not intent and not outcome and not learned:
            continue

        if intent:
            turns.append(Turn(role="user", text=_clip(intent, MAX_MSG_CHARS), ts=ts))
        if isinstance(actions, list) and actions:
            turns.append(Turn(role="tool", text=_clip(_bullets(actions), MAX_MSG_CHARS), ts=ts))
        if outcome:
            turns.append(Turn(role="assistant", text=_clip(outcome, MAX_MSG_CHARS), ts=ts))
        if isinstance(learned, list) and learned:
            turns.append(Turn(role="assistant", text=_clip("learned:\n" + _bullets(learned), MAX_MSG_CHARS), ts=ts))

    if not turns:
        return None, end_offset
    return (
        Transcript(
            session_id=session_id,
            cwd=cwd,
            started_at=started_at,
            source_file=str(path),
            turns=turns,
        ),
        end_offset,
    )


def render_transcript(t: Transcript) -> str:
    """Render a condensed, token-bounded transcript for the distill prompt."""
    lines = [
        f"# Session {t.session_id}",
        f"# project: {t.cwd}",
        f"# started: {t.started_at}",
        "",
    ]
    role_label = {"user": "USER", "assistant": "ASSISTANT", "tool": "ACTIONS"}
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
