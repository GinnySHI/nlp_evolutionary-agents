"""Minimal English CLI for group chats, private messages and evaluation."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from contextlib import contextmanager
from pathlib import Path

from .config import Settings, read_env
from .provider import HKGAIClient, ProviderError
from .scenarios import SCENARIOS, scenario


def dump(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def session_path(settings: Settings, name: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name):
        raise ValueError("Session names must contain 1–80 letters, digits, underscores or hyphens.")
    root = settings.data_dir / "sessions" / name
    if root.is_symlink():
        raise ValueError("Session directory cannot be a symlink.")
    return root


@contextmanager
def exclusive_session(root: Path):
    """Avoid concurrent writers to a resumable session; Unix host only."""
    import fcntl
    root.parent.mkdir(parents=True, exist_ok=True)
    with (root.parent / f".{root.name}.lock").open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("This session is running in another process.") from None
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def show_status(engine) -> None:
    state = engine.status()
    print(f"\nStatus: {state.get('status', engine.state.get('status'))}")
    if engine.state.get("final_output"):
        print(f"\nFinal output:\n{engine.state['final_output']}")
    pending = engine.state.get("pending")
    if pending:
        print("\nHuman input required:")
        dump(pending)
    print("\nMetrics:")
    dump(state.get("metrics", engine.state.get("metrics", {})))
    print(f"Session files: {engine.root}")


def event_printer(event: dict) -> None:
    kind = event.get("kind", event.get("type", event.get("event", "event")))
    agent = event.get("agent_id", event.get("sender", event.get("agent", "system")))
    action = event.get("action", "")
    if isinstance(action, dict):
        action = action.get("action", "")
    print(f"[{agent}] {kind}{': ' + str(action) if action else ''}", flush=True)
    if kind == "message" and event.get("content"):
        print(str(event["content"]), flush=True)


def drive(engine, *, interactive: bool) -> None:
    while engine.state.get("status") == "waiting_human" and interactive:
        pending = engine.state.get("pending") or {}
        print("\nHuman input required:")
        dump(pending)
        try:
            if pending.get("type") == "tool_approval":
                answer = input("Approve this exact operation? [yes/no/pause]: ").strip().lower()
                if answer == "pause" or answer == "":
                    break
                if answer not in {"yes", "no"}:
                    print("Enter yes, no or pause.")
                    continue
                engine.respond("Approved by user." if answer == "yes" else "Denied by user.", approved=answer == "yes")
            else:
                answer = input("Your answer (blank to pause): ").strip()
                if not answer:
                    break
                engine.respond(answer)
        except (EOFError, KeyboardInterrupt):
            print("\nPaused. Session state is saved.")
            break
    show_status(engine)


def chat(engine) -> None:
    print("Group chat ready. Commands: /task TEXT, /dm AGENT TEXT, /run [STEPS], /answer TEXT,")
    print("/approve, /deny, /status, /quit. Plain text starts a task or answers a pending question.")
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession saved.")
            return
        if not line:
            continue
        command, _, body = line.partition(" ")
        try:
            if command == "/quit":
                return
            if command == "/status":
                show_status(engine)
            elif command == "/dm":
                agent, _, message = body.partition(" ")
                if not message:
                    raise ValueError("Usage: /dm AGENT MESSAGE")
                print(engine.direct_message(agent, message))
            elif command == "/approve" or command == "/deny":
                engine.respond(body or command[1:], approved=command == "/approve")
                drive(engine, interactive=True)
            elif command == "/answer":
                engine.respond(body)
                drive(engine, interactive=True)
            elif command == "/run":
                engine.run(max_steps=int(body) if body else None)
                drive(engine, interactive=True)
            elif command == "/task" or not line.startswith("/"):
                text = body if command == "/task" else line
                if engine.state.get("status") == "waiting_human" and command != "/task":
                    engine.respond(text)
                else:
                    engine.start_task(text)
                    engine.run()
                drive(engine, interactive=True)
            else:
                print("Unknown command. Use /status or /quit.")
        except (ValueError, RuntimeError, OSError) as exc:
            print(f"Error: {exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evo", description="Evolutionary multi-agent collaboration with HKGAI / DeepSeek.")
    parser.add_argument("--env", type=Path, default=None, help="Local environment file (default: .env in current directory)")
    subs = parser.add_subparsers(dest="command", required=True)
    init = subs.add_parser("init", help="Create an isolated team session")
    init.add_argument("name")
    init.add_argument("--scenario", choices=SCENARIOS, default="software")
    init.add_argument("--agents", type=Path, help="Optional JSON list of agents with id, name, role and optional allowed_tools")
    run = subs.add_parser("run", help="Start a task or resume a session")
    run.add_argument("name")
    group = run.add_mutually_exclusive_group()
    group.add_argument("--task", help="New task text")
    group.add_argument("--task-file", type=Path, help="New task from a .md or .txt file")
    run.add_argument("--steps", type=int, help="Additional execution step budget")
    run.add_argument("--interactive", action="store_true", help="Prompt for clarification and approvals")
    interact = subs.add_parser("chat", help="Interactive group chat and private messages")
    interact.add_argument("name")
    reply = subs.add_parser("respond", help="Answer a paused human request")
    reply.add_argument("name")
    reply.add_argument("text", nargs="?", default="")
    approve = reply.add_mutually_exclusive_group()
    approve.add_argument("--approve", action="store_true")
    approve.add_argument("--deny", action="store_true")
    reply.add_argument("--interactive", action="store_true")
    dm = subs.add_parser("dm", help="Send a private message to one agent")
    dm.add_argument("name")
    dm.add_argument("agent")
    dm.add_argument("message")
    status = subs.add_parser("status", help="Read saved session state without API calls")
    status.add_argument("name")
    subs.add_parser("sessions", help="List saved sessions without API calls")
    sc = subs.add_parser("scenarios", help="Show built-in role definitions and task prompts")
    sc.add_argument("name", nargs="?", choices=SCENARIOS)
    doctor = subs.add_parser("doctor", help="Check configuration and sandbox executables")
    doctor.add_argument("--live", action="store_true", help="Make one small paid API request")
    evaluation = subs.add_parser("evaluate", help="Run a JSON evaluation dataset; never auto-approve tools")
    evaluation.add_argument("dataset", type=Path)
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument("--steps", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = None
    try:
        settings = Settings.from_env(args.env)
        # This token is read only by an approved Git push; never stored in session JSON.
        optional = read_env((args.env or Path.cwd() / ".env").resolve()).get("EVO_GITHUB_TOKEN")
        if optional and "EVO_GITHUB_TOKEN" not in os.environ:
            os.environ["EVO_GITHUB_TOKEN"] = optional
        if args.command == "scenarios":
            dump(scenario(args.name) if args.name else {k: v["title"] for k, v in SCENARIOS.items()})
            return 0
        if args.command == "doctor":
            import platform
            import shutil
            print(f"Python: {sys.version.split()[0]}")
            print(f"API base: {settings.base_url}")
            print(f"Model: {settings.model}")
            print(f"API key configured: {bool(settings.api_key)}")
            print(f"Provider: {settings.provider}")
            print(f"DeepSeek fallback ready: {settings.fallback_enabled and bool(settings.deepseek_api_key) and settings.provider == 'hkgai'}")
            print(f"Sandbox preference: {settings.sandbox_backend}")
            print(f"Docker executable: {bool(shutil.which('docker'))}")
            print(f"macOS sandbox executable: {platform.system() == 'Darwin' and bool(shutil.which('sandbox-exec'))}")
            if args.live:
                client = HKGAIClient(settings)
                print("API response:", client.complete([{"role": "user", "content": "Reply with exactly HKGAI_OK."}], json_mode=False))
                print(f"Active provider: {getattr(client, 'active_provider', settings.provider)}")
                dump(dict(client.stats))
            return 0
        if args.command == "sessions":
            base = settings.data_dir / "sessions"
            dump([p.name for p in sorted(base.iterdir()) if p.is_dir() and not p.is_symlink()] if base.exists() else [])
            return 0
        if args.command == "status":
            state = json.loads((session_path(settings, args.name) / "state.json").read_text(encoding="utf-8"))
            dump({k: state.get(k) for k in ("title", "status", "task", "tasks", "pending", "final_output", "metrics")})
            return 0
        if args.command == "init":
            from .engine import AgentSpec, SessionEngine
            root = session_path(settings, args.name)
            setup = scenario(args.scenario)
            specs = json.loads(args.agents.read_text(encoding="utf-8")) if args.agents else setup["agents"]
            if not isinstance(specs, list) or any(
                not isinstance(item, dict) or set(item) - {"id", "name", "role", "allowed_tools"} or
                any(not isinstance(item.get(field), str) or not item[field].strip() for field in ("id", "name", "role"))
                for item in specs
            ):
                raise ValueError("Custom agents require nonempty string id, name and role fields and accept optional allowed_tools.")
            agents = [AgentSpec(**item) for item in specs]
            with exclusive_session(root):
                SessionEngine.create(root, agents, None, title=setup["title"],
                                     sandbox_backend=settings.sandbox_backend, max_steps=settings.max_steps)
            print(f"Created session: {args.name}\nLocation: {root}\nNext: evo chat {shlex.quote(args.name)}")
            return 0
        client = HKGAIClient(settings)
        if args.command == "evaluate":
            from .evaluation import evaluate
            result = evaluate(args.dataset, args.output, client, sandbox_backend=settings.sandbox_backend,
                              max_steps=args.steps or settings.max_steps)
            dump(result["summary"])
            print(f"Report: {args.output.resolve() / 'report.md'}")
            return 0 if result["summary"]["verified_successes"] == result["summary"]["case_count"] else 2
        from .engine import SessionEngine
        root = session_path(settings, args.name)
        with exclusive_session(root):
            engine = SessionEngine.load(root, client)
            engine.on_event = event_printer
            if args.command == "chat":
                chat(engine)
            elif args.command == "dm":
                print(engine.direct_message(args.agent, args.message))
            elif args.command == "respond":
                approved = True if args.approve else False if args.deny else None
                engine.respond(args.text, approved=approved)
                drive(engine, interactive=args.interactive)
            elif args.command == "run":
                text = args.task
                if args.task_file:
                    if args.task_file.suffix.lower() not in {".md", ".txt"}:
                        raise ValueError("Task documents must be .md or .txt files.")
                    text = args.task_file.read_text(encoding="utf-8")
                if text:
                    engine.start_task(text)
                engine.run(max_steps=args.steps)
                drive(engine, interactive=args.interactive)
            return 0 if engine.state.get("status") in {"idle", "completed"} or args.command in {"dm", "chat"} else 2
    except (ValueError, KeyError, TypeError, OSError, RuntimeError, ProviderError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted. Use status to inspect saved progress.", file=sys.stderr)
        return 130
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    raise SystemExit(main())
