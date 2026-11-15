"""Per-agent, explicit-scope episodic memory with bounded lexical retrieval.

Memory changes future prompts, not model weights. Group retrieval never reads
the private channel, even when both channels belong to the same agent.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(value: Any) -> Any:
    """Keep likely API credentials out of durable traces and prompts."""
    if isinstance(value, str):
        value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}", "[REDACTED_API_KEY]", value)
        return re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]", value)
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if str(key).lower() in {"api_key", "apikey", "authorization", "access_token", "password"} else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    line = json.dumps(redact(record), ensure_ascii=False, allow_nan=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(line)
        stream.flush()
        os.fsync(stream.fileno())


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(redact(value), stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _tokens(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_]{2,}", text.lower()))
    # Character bigrams make a small local index useful for Chinese queries too.
    for phrase in re.findall(r"[\u3400-\u9fff]+", text):
        words.update(phrase[i:i + 2] for i in range(max(1, len(phrase) - 1)))
    return words


class AgentMemory:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _path(self, scope: str) -> Path:
        if scope not in {"group", "private"}:
            raise ValueError("Memory scope must be group or private.")
        return self.directory / f"{scope}.jsonl"

    def add(self, text: str, *, kind: str = "lesson", scope: str = "group", task_id: str | None = None,
            outcome: str | None = None, evidence: Any = None) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Memory content cannot be empty.")
        record = redact({"id": uuid4().hex, "created_at": utc_now(), "kind": kind, "scope": scope,
                         "text": text[:6000], "task_id": task_id, "outcome": outcome, "evidence": evidence})
        append_jsonl(self._path(scope), record)
        return record

    def entries(self, *, scope: str = "group", limit: int = 2000) -> list[dict[str, Any]]:
        path = self._path(scope)
        if not path.exists():
            return []
        # A partially written final line after power loss must not destroy older memory.
        records: list[dict[str, Any]] = []
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(item, dict) and item.get("scope") == scope and isinstance(item.get("text"), str):
                    records.append(item)
                if len(records) > limit * 2:
                    records = records[-limit:]
        return records[-limit:]

    def retrieve(self, query: str, *, scope: str = "group", limit: int = 6) -> list[dict[str, Any]]:
        if not 1 <= limit <= 30:
            raise ValueError("Memory retrieval limit must be between 1 and 30.")
        entries = self.entries(scope=scope)
        query_tokens = _tokens(query)
        ranked = []
        for index, item in enumerate(entries):
            tokens = _tokens(item["text"])
            similarity = len(query_tokens & tokens) / max(1, len(query_tokens | tokens))
            # Relevant lessons dominate; a slight recency preference breaks ties.
            score = similarity + (0.025 if item.get("kind") == "lesson" else 0) + 0.005 * (index + 1) / max(1, len(entries))
            ranked.append((score, index, item))
        ranked.sort(key=lambda value: (value[0], value[1]), reverse=True)
        return [item for _, _, item in ranked[:limit]]

    def stats(self) -> dict[str, int]:
        group = self.entries(scope="group")
        return {"group_entries": len(group), "lessons": sum(item.get("kind") == "lesson" for item in group),
                "successes": sum(item.get("kind") == "episode" and item.get("outcome") == "accepted" for item in group),
                "failures": sum(item.get("kind") == "episode" and item.get("outcome") == "failed" for item in group)}
