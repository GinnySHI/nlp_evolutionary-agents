#!/usr/bin/env python3
"""Snapshot measured run evidence for the course performance report.

Reads only saved session state. Makes no API calls and never edits a
deliverable: it records what the run actually produced, with hashes, so the
report quotes measured values instead of recollections.

Usage: python scripts/collect_evidence.py SESSION_DIR... --output DIR
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

METRIC_KEYS = ("elapsed_seconds", "active_seconds", "agent_turns", "tool_calls", "tool_errors",
               "invalid_actions", "recovered_responses", "output_limit_errors", "fatal_errors",
               "subtasks_total", "subtasks_accepted", "subtask_completion_rate",
               "model_claimed_success", "peer_reviewed_completion", "checkpoints",
               "reflection_calls", "reflection_failures", "normalized_actions")


def digest(path: Path) -> dict:
    data = path.read_bytes()
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def workspace_files(session: Path) -> dict:
    out: dict[str, dict] = {}
    agents = session / "agents"
    if not agents.exists():
        return out
    for item in sorted(agents.rglob("*")):
        if item.is_file() and not item.is_symlink():
            out[item.relative_to(agents).as_posix()] = digest(item)
    return out


def event_counts(session: Path) -> dict:
    counts: dict[str, int] = {}
    path = session / "events.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                kind = json.loads(line).get("kind")
            except ValueError:
                continue
            if isinstance(kind, str):
                counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def human_turns(session: Path) -> list[dict]:
    """Every real human intervention, so HITL is auditable rather than asserted."""
    turns = []
    path = session / "events.jsonl"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("kind") == "human_question":
                turns.append({"time": event.get("time"), "type": "question",
                              "agent_id": event.get("agent_id"), "text": (event.get("question") or "")[:4000]})
            elif event.get("kind") == "approval_requested":
                turns.append({"time": event.get("time"), "type": "approval_requested",
                              "agent_id": event.get("agent_id"),
                              "tool": (event.get("tool") or {}).get("name")})
            elif event.get("kind") == "approval_resolved":
                turns.append({"time": event.get("time"), "type": "approval_resolved",
                              "agent_id": event.get("agent_id"), "approved": event.get("approved")})
            elif event.get("kind") == "message" and event.get("sender") == "human":
                turns.append({"time": event.get("time"), "type": "human_reply",
                              "to": event.get("recipient"), "text": (event.get("content") or "")[:4000]})
    return turns


def snapshot(session: Path) -> dict:
    state = json.loads((session / "state.json").read_text(encoding="utf-8"))
    metrics = state.get("metrics") or {}
    runs = []
    runs_dir = session / "runs"
    if runs_dir.exists():
        for item in sorted(runs_dir.glob("*.json")):
            archived = json.loads(item.read_text(encoding="utf-8"))
            archived_metrics = archived.get("metrics") or {}
            runs.append({"task_id": archived.get("task_id"), "status": archived.get("status"),
                         "task": (archived.get("task") or "")[:400],
                         "final_output": (archived.get("final_output") or "")[:2000],
                         "metrics": {k: archived_metrics.get(k) for k in METRIC_KEYS},
                         "provider": archived_metrics.get("provider"),
                         "subtasks": [{"id": t["id"], "assignee": t["assignee"], "status": t["status"],
                                       "review": t.get("review")} for t in archived.get("tasks", [])]})
    return {
        "session": session.name,
        "title": state.get("title"),
        "agents": [{"id": a["id"], "name": a["name"], "allowed_tools": a.get("allowed_tools")}
                   for a in state.get("agents", [])],
        "archived_runs": runs,
        "current_run": {
            "task_id": state.get("task_id"), "status": state.get("status"),
            "task": (state.get("task") or "")[:400],
            "final_output": (state.get("final_output") or "")[:2000],
            "metrics": {k: metrics.get(k) for k in METRIC_KEYS},
            "provider": metrics.get("provider"),
            "memory": metrics.get("memory"),
            "subtasks": [{"id": t["id"], "assignee": t["assignee"], "status": t["status"],
                          "review": t.get("review")} for t in state.get("tasks", [])],
            "pending": state.get("pending"),
        },
        "event_counts": event_counts(session),
        "human_interventions": human_turns(session),
        "workspace_files": workspace_files(session),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("sessions", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    combined = {}
    for session in args.sessions:
        if not (session / "state.json").exists():
            print(f"skip {session}: no state.json")
            continue
        data = snapshot(session)
        combined[session.name] = data
        (args.output / f"{session.name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        current = data["current_run"]
        print(f"{session.name}: {current['status']} "
              f"turns={current['metrics'].get('agent_turns')} "
              f"accepted={current['metrics'].get('subtasks_accepted')}/{current['metrics'].get('subtasks_total')} "
              f"archived_runs={len(data['archived_runs'])} files={len(data['workspace_files'])}")
    (args.output / "all-sessions.json").write_text(
        json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
