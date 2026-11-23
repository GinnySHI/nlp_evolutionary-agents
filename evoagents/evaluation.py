"""Auditable evaluation: separate peer claims from independent artifact checks."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .engine import AgentSpec, SessionEngine
from .scenarios import scenario


def check_artifacts(engine: SessionEngine, checks: list[dict]) -> list[dict]:
    outcomes = []
    for check in checks:
        if not isinstance(check, dict):
            outcomes.append({"check": check, "passed": False, "error": "Invalid check object"})
            continue
        kind = check.get("type")
        result = {"check": check, "passed": False}
        try:
            if kind not in {"file_exists", "text_contains", "text_equals"}:
                raise ValueError("未知验收类型")
            read = engine.tools.execute(check["agent"], "read_file", {"path": check["path"]})
            if read.get("ok") is False:
                raise ValueError(read.get("error", "无法读取文件"))
            # read_file returns content at top level (the shared tool contract).
            content = read.get("content")
            if not isinstance(content, str):
                raise ValueError("读取结果没有文本内容")
            if kind == "text_equals" and read.get("truncated"):
                raise ValueError("Full-text equality cannot be verified because the file result was truncated")
            if kind == "file_exists":
                result["passed"] = True
            elif kind == "text_contains":
                result["passed"] = check["text"] in content
            else:
                result["passed"] = content.rstrip("\n") == check["text"].rstrip("\n")
        except (ValueError, KeyError, TypeError, OSError, RuntimeError) as exc:
            result["error"] = str(exc)[:500]
        outcomes.append(result)
    return outcomes


def evaluate(dataset: Path, output: Path, client, *, sandbox_backend="auto", max_steps=40) -> dict:
    data = json.loads(dataset.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("The dataset must be a JSON object")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("The dataset must contain a nonempty cases array")
    seen_ids = set()
    sessions = {}
    for index, case in enumerate(cases, 1):
        if not isinstance(case, dict) or not isinstance(case.get("task"), str) or not case["task"].strip():
            raise ValueError("Each case must contain nonempty task text")
        case_id = str(case.get("id", f"case-{index}"))
        session = str(case.get("session", case_id))
        if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", value) for value in (case_id, session)):
            raise ValueError("Case and session IDs must be simple ASCII identifiers")
        if case_id in seen_ids:
            raise ValueError("Case IDs must be unique")
        seen_ids.add(case_id)
        selected = case.get("scenario", "smoke")
        setup = scenario(selected)
        if session in sessions and sessions[session] != selected:
            raise ValueError("Cases sharing a session must use the same scenario")
        sessions[session] = selected
        if not isinstance(case.get("checks", []), list) or not isinstance(case.get("human_responses", []), list):
            raise ValueError("checks and human_responses must be arrays")
        if any(not isinstance(response, str) or not response.strip() for response in case.get("human_responses", [])):
            raise ValueError("Human responses must be nonempty strings")
        for check in case.get("checks", []):
            if not isinstance(check, dict) or check.get("type") not in {"file_exists", "text_contains", "text_equals"}:
                raise ValueError("Checks must be objects of type file_exists, text_contains or text_equals")
            if check.get("agent") not in {item["id"] for item in setup["agents"]}:
                raise ValueError("Check refers to an unknown agent")
            if not isinstance(check.get("path"), str) or not check["path"] or Path(check["path"]).is_absolute() or ".." in Path(check["path"]).parts:
                raise ValueError("Check path must be a nonempty workspace-relative file path")
            if check["type"] != "file_exists" and not isinstance(check.get("text"), str):
                raise ValueError("Text checks require a string text field")
    if output.exists():
        raise ValueError("Evaluation output directory already exists; choose a new directory")
    output.mkdir(parents=True)
    started = time.monotonic()
    rows = []
    teams = {}
    for index, case in enumerate(cases, 1):
        case_id = str(case.get("id", f"case-{index}"))
        setup = scenario(case.get("scenario", "smoke"))
        session = str(case.get("session", case_id))
        if session not in teams:
            teams[session] = SessionEngine.create(
                output / "sessions" / session, [AgentSpec(**a) for a in setup["agents"]], client,
                title=session, sandbox_backend=sandbox_backend, max_steps=max_steps,
            )
        engine = teams[session]
        print(f"Evaluating {case_id} (session: {session})...", flush=True)
        if engine.state["status"] not in {"idle", "completed", "failed"}:
            rows.append({"id": case_id, "session": session, "status": "blocked_by_previous_case", "metrics": {},
                         "checks": [], "verified_success": False, "requires_manual_review": not bool(case.get("checks")),
                         "pending": engine.state.get("pending")})
            continue
        memory_before = {agent: memory.stats() for agent, memory in engine.memories.items()}
        engine.start_task(case["task"])
        engine.run()
        # Batch evaluation never invents human approval. Missing responses remain pending.
        for response in case.get("human_responses", []):
            if engine.state["status"] != "waiting_human":
                break
            pending = engine.state.get("pending") or {}
            if pending.get("type") == "tool_approval":
                break
            engine.respond(str(response))
        checks = check_artifacts(engine, case.get("checks", []))
        finished = engine.state["status"] == "completed"
        independently_verified = finished and bool(checks) and all(item["passed"] for item in checks)
        rows.append({
            "id": case_id, "session": session, "status": engine.state["status"], "metrics": engine.status().get("metrics", {}),
            "checks": checks, "verified_success": independently_verified,
            "requires_manual_review": not bool(checks),
            "pending": engine.state.get("pending"),
            "memory_before": memory_before,
            "memory_after": {agent: memory.stats() for agent, memory in engine.memories.items()},
        })
        (output / "results.json").write_text(json.dumps({"cases": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    accepted = sum(r["metrics"].get("subtasks_accepted", 0) for r in rows)
    total_subtasks = sum(r["metrics"].get("subtasks_total", 0) for r in rows)
    summary = {
        "case_count": len(rows), "verified_successes": sum(r["verified_success"] for r in rows),
        "verified_task_completion_rate": sum(r["verified_success"] for r in rows) / len(rows),
        "peer_reviewed_subtask_completion_rate": accepted / total_subtasks if total_subtasks else 0,
        "total_elapsed_seconds": round(time.monotonic() - started, 3),
        "manual_review_cases": sum(r["requires_manual_review"] for r in rows),
        "human_pending_cases": sum(r["status"] == "waiting_human" for r in rows),
        "fatal_errors": sum(r["metrics"].get("fatal_errors", 0) for r in rows),
    }
    result = {"summary": summary, "cases": rows}
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 多智能体系统评测报告", "", "同伴审核与独立验收分别计数；未配置独立验收的案例需要人工评分。", "",
             f"- 案例数：{len(rows)}", f"- 独立验收通过率：{summary['verified_task_completion_rate']:.1%}",
             f"- 同伴审核子任务通过率：{summary['peer_reviewed_subtask_completion_rate']:.1%}",
             f"- 总执行时间：{summary['total_elapsed_seconds']} 秒", f"- 致命错误：{summary['fatal_errors']}", "",
             "| 案例 | 状态 | 独立验收通过 | 耗时（秒） |", "|---|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['id']} | {row['status']} | {row['verified_success']} | {row['metrics'].get('elapsed_seconds', 0)} |")
    lines.extend(["", "每个案例目录保留完整会话、独立工作区与记忆。人工等待案例不能算作成功；批量评测不会自动批准代码执行、删除或 Git 写操作。", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return result
