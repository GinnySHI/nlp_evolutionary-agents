import hashlib
import json
import os
from pathlib import Path
import socket
import signal
from unittest.mock import patch

import httpx
import pytest

from evoagents.tools import MAX_FILE_BYTES, ToolError, ToolRunner, _public_target


@pytest.fixture
def runner(tmp_path):
    return ToolRunner(tmp_path / "agents", agent_ids=["lead", "dev", "qa"])


def write(runner, agent="dev", path="notes.md", content="Hello 世界"):
    result = runner.execute(agent, "write_file", {"path": path, "content": content})
    assert result["ok"], result
    return result


def test_roundtrip_nested_utf8_and_list(runner):
    write(runner, path="src/app.py", content="print('Hello 世界')")
    result = runner.execute("dev", "read_file", {"path": "src/app.py"})
    assert result["content"] == "print('Hello 世界')"
    assert runner.execute("dev", "list_files", {})["files"][0]["path"] == "src/app.py"
    assert runner.execute("qa", "list_files", {})["files"] == []


@pytest.mark.parametrize("path", ["../qa/workspace/secret.txt", "/etc/passwd", "src/../../x.py", r"C:\secret.txt", ".git/config", "x/../y.txt"])
def test_path_escape_rejected(runner, path):
    assert not runner.execute("dev", "write_file", {"path": path, "content": "x"})["ok"]
    assert not runner.execute("dev", "read_file", {"path": path})["ok"]


@pytest.mark.parametrize("path", ["report.pdf", "essay.docx", "talk.pptx", "data.xlsx", "image.png", ".env"])
def test_unsupported_document_types_rejected(runner, path):
    assert not runner.execute("dev", "write_file", {"path": path, "content": "x"})["ok"]


def test_symlink_and_hardlink_boundaries(runner, tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("private", encoding="utf-8")
    workspace = runner.workspace("dev")
    (workspace / "link.txt").symlink_to(secret)
    (workspace / "parent").symlink_to(tmp_path, target_is_directory=True)
    os.link(secret, workspace / "hard.txt")
    for path in ["link.txt", "parent/secret.txt", "hard.txt"]:
        assert not runner.execute("dev", "read_file", {"path": path})["ok"]
        assert not runner.execute("dev", "write_file", {"path": path, "content": "changed"})["ok"]
        assert not runner.execute("dev", "delete_file", {"path": path}, approved=True)["ok"]
    assert secret.read_text() == "private"


def test_fifo_rejected_without_blocking(runner):
    os.mkfifo(runner.workspace("dev") / "fifo.txt")
    assert not runner.execute("dev", "read_file", {"path": "fifo.txt"})["ok"]


def test_files_have_size_limit(runner):
    assert not runner.execute("dev", "write_file", {"path": "huge.txt", "content": "x" * (MAX_FILE_BYTES + 1)})["ok"]
    (runner.workspace("dev") / "huge.txt").write_text("x" * (MAX_FILE_BYTES + 1))
    assert not runner.execute("dev", "read_file", {"path": "huge.txt"})["ok"]


def test_approval_is_required_for_all_critical_operations(runner):
    write(runner)
    calls = [("delete_file", {"path": "notes.md"}), ("run_python", {"path": "script.py"}),
             ("git_commit", {"message": "test"}), ("git_push", {"remote_url": "https://github.com/a/b", "branch": "main"})]
    for tool, args in calls:
        response = runner.execute("dev", tool, args)
        assert response["approval_required"], response
    assert (runner.workspace("dev") / "notes.md").exists()
    assert runner.execute("dev", "delete_file", {"path": "notes.md"}, approved=True)["ok"]


def test_exact_schema_and_agent_validation(runner):
    assert not runner.execute("other", "list_files", {})["ok"]
    assert not runner.execute("dev", "read_file", {})["ok"]
    assert not runner.execute("dev", "write_file", {"path": "a.txt", "content": 7})["ok"]
    assert not runner.execute("dev", "run_python", {"path": "a.py", "timeout": True}, approved=True)["ok"]
    assert not runner.execute("dev", "run_python", {"path": "a.py", "timeout": float("nan")}, approved=True)["ok"]
    assert not runner.execute("dev", "list_files", {"shell": "rm -rf /"})["ok"]


def test_share_explicit_file_only_with_audited_hash(runner):
    write(runner, path="output/report.md", content="A report")
    write(runner, path="private.txt", content="Do not share")
    result = runner.execute("dev", "send_file", {"recipient": "qa", "path": "output/report.md", "destination": "report.md"})
    assert result["ok"], result
    assert result["sha256"] == hashlib.sha256(b"A report").hexdigest()
    assert result["destination"] == "inbox/dev/report.md"
    assert runner.execute("qa", "read_file", {"path": result["destination"]})["content"] == "A report"
    assert not runner.execute("qa", "read_file", {"path": "private.txt"})["ok"]
    assert not runner.execute("dev", "send_file", {"recipient": "qa", "path": "private.txt", "destination": "report.md"})["ok"]
    receipts = (runner.root / "transfers.jsonl").read_text().splitlines()
    assert len(receipts) == 1 and json.loads(receipts[0])["recipient"] == "qa"


def dns(addresses):
    return [(socket.AF_INET6 if ":" in addr else socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 443)) for addr in addresses]


@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"], ["192.168.1.1"], ["93.184.216.34", "10.0.0.1"], ["224.0.0.1"], ["::ffff:127.0.0.1"]])
def test_private_or_mixed_dns_answers_blocked(addresses):
    with patch("evoagents.tools.socket.getaddrinfo", return_value=dns(addresses)):
        with pytest.raises(ToolError):
            _public_target("https://example.test/page")


def test_public_dns_is_pinned_and_tls_retains_original_hostname():
    with patch("evoagents.tools.socket.getaddrinfo", return_value=dns(["93.184.216.34"])):
        pinned, host, sni = _public_target("https://example.test/path?q=hi#anchor")
    assert pinned == "https://93.184.216.34:443/path?q=hi"
    assert host == sni == "example.test"


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://user:pass@example.org", "http://example.org:9999", "ftp://example.org/x", "https://example.org/\nheader"])
def test_invalid_network_urls_blocked(url):
    with pytest.raises(ToolError):
        _public_target(url)


def test_redirect_is_revalidated_and_local_destination_never_requested(runner, monkeypatch):
    calls = []
    actual_client = httpx.Client

    def lookup(host, port, type):
        return dns(["127.0.0.1"] if host == "localhost" else ["93.184.216.34"])

    def handle(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "http://localhost/secret"})

    monkeypatch.setattr("evoagents.tools.socket.getaddrinfo", lookup)
    monkeypatch.setattr("evoagents.tools.httpx.Client", lambda **kw: actual_client(transport=httpx.MockTransport(handle), **kw))
    result = runner.execute("dev", "fetch_url", {"url": "https://example.test"})
    assert not result["ok"]
    assert len(calls) == 1
    assert calls[0].url.host == "93.184.216.34"
    assert calls[0].headers["host"] == "example.test"
    assert calls[0].extensions["sni_hostname"] == "example.test"


def test_fetch_strips_script_and_marks_evidence_untrusted(runner, monkeypatch):
    actual_client = httpx.Client
    monkeypatch.setattr("evoagents.tools.socket.getaddrinfo", lambda *a, **k: dns(["93.184.216.34"]))
    monkeypatch.setattr("evoagents.tools.httpx.Client", lambda **kw: actual_client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text="<h1>News</h1><script>SECRET()</script><p>Article</p>")), **kw))
    result = runner.execute("dev", "fetch_url", {"url": "https://example.test"})
    assert result["ok"] and result["untrusted"]
    assert "News" in result["content"] and "Article" in result["content"] and "SECRET" not in result["content"]


@pytest.mark.parametrize("headers, body", [({"content-type": "application/pdf"}, b"%PDF"), ({"content-type": "text/plain", "content-encoding": "br"}, b"")])
def test_binary_and_unexpected_compression_rejected(runner, monkeypatch, headers, body):
    actual_client = httpx.Client
    monkeypatch.setattr("evoagents.tools.socket.getaddrinfo", lambda *a, **k: dns(["93.184.216.34"]))
    monkeypatch.setattr("evoagents.tools.httpx.Client", lambda **kw: actual_client(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, headers=headers, content=body)), **kw))
    assert not runner.execute("dev", "fetch_url", {"url": "https://example.test"})["ok"]


def test_search_returns_citable_rss_items(runner, monkeypatch):
    monkeypatch.setattr(runner, "_http_fetch", lambda url: {"content": "<rss><channel><item><title>A study</title><link>https://example.org/study</link><description>Evidence</description></item></channel></rss>", "truncated": False, "retrieved_at": 123})
    result = runner.execute("dev", "search_web", {"query": "AI detection research", "limit": 1})
    assert result["ok"] and result["untrusted"] and result["results"][0]["url"] == "https://example.org/study"


def test_run_python_uses_sandbox_only(runner, monkeypatch):
    called = []

    class StubSandbox:
        def __init__(self, workspace, backend):
            called.append((workspace, backend))

        def run_python(self, path, timeout):
            called.append((path, timeout))
            return {"ok": True, "stdout": "isolated"}

    monkeypatch.setattr("evoagents.tools.Sandbox", StubSandbox)
    result = runner.execute("dev", "run_python", {"path": "app.py", "timeout": 12}, approved=True)
    assert result["stdout"] == "isolated"
    assert called[0] == (runner.workspace("dev"), "auto")
    assert called[1] == ("app.py", 12)


def test_git_init_commit_status_and_diff(runner):
    result = runner.execute("dev", "git_init", {})
    assert result["ok"], result
    write(runner, path="README.md", content="First")
    result = runner.execute("dev", "git_commit", {"message": "Add README"}, approved=True)
    assert result["ok"], result
    assert runner.execute("dev", "git_status", {})["stdout"] == ""
    write(runner, path="README.md", content="Second")
    result = runner.execute("dev", "git_diff", {})
    assert result["ok"] and "+Second" in result["unstaged"]["stdout"]


def test_git_hooks_and_environment_credentials_are_not_inherited(runner, monkeypatch, tmp_path):
    monkeypatch.setenv("HKGAI_API_KEY", "test-api-secret")
    monkeypatch.setenv("EVO_GITHUB_TOKEN", "test-github-secret")
    env = runner._git_environment("dev")
    assert "HKGAI_API_KEY" not in env and "EVO_GITHUB_TOKEN" not in env
    assert runner.execute("dev", "git_init", {})["ok"]
    hook = runner.workspace("dev") / ".git/hooks/pre-commit"
    hook.parent.mkdir(exist_ok=True)
    sentinel = tmp_path / "hook-ran"
    hook.write_text(f"#!/bin/sh\ntouch '{sentinel}'\nexit 1\n")
    hook.chmod(0o755)
    write(runner)
    assert runner.execute("dev", "git_commit", {"message": "Safe commit"}, approved=True)["ok"]
    assert not sentinel.exists()


def test_malicious_git_config_rejected_before_commands(runner, tmp_path):
    assert runner.execute("dev", "git_init", {})["ok"]
    config = runner.workspace("dev") / ".git/config"
    with config.open("a") as stream:
        stream.write('\n[include]\n\tpath = /etc/passwd\n')
    result = runner.execute("dev", "git_status", {})
    assert not result["ok"] and "configuration" in result["error"].lower()


@pytest.mark.parametrize("remote, branch", [("file:///tmp/repo", "main"), ("https://github.com.evil.test/a/b", "main"), ("https://token@github.com/a/b", "main"), ("https://github.com/a/b", "--force"), ("https://github.com/a/b", "bad..branch")])
def test_push_restricts_remote_and_ref(runner, remote, branch):
    assert runner.execute("dev", "git_init", {})["ok"]
    result = runner.execute("dev", "git_push", {"remote_url": remote, "branch": branch}, approved=True)
    assert not result["ok"]


def test_push_without_token_explains_configuration(runner, monkeypatch):
    monkeypatch.delenv("EVO_GITHUB_TOKEN", raising=False)
    assert runner.execute("dev", "git_init", {})["ok"]
    result = runner.execute("dev", "git_push", {"remote_url": "https://github.com/example/project", "branch": "main"}, approved=True)
    assert not result["ok"] and "EVO_GITHUB_TOKEN" in result["error"]


def test_sanitized_error_does_not_expose_token(runner, monkeypatch):
    monkeypatch.setenv("EVO_GITHUB_TOKEN", "a-sensitive-token")
    monkeypatch.setattr(runner, "_search", lambda *args: (_ for _ in ()).throw(ToolError("failure a-sensitive-token")))
    result = runner.execute("dev", "search_web", {"query": "test"})
    assert "a-sensitive-token" not in result["error"] and "[REDACTED]" in result["error"]


def test_interrupted_git_process_is_killed_and_reaped(runner, monkeypatch):
    events = []

    class InterruptedProcess:
        pid = 87654

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            if timeout is not None:
                raise KeyboardInterrupt
            return -signal.SIGKILL

    monkeypatch.setattr("evoagents.tools.subprocess.Popen", lambda *args, **kwargs: InterruptedProcess())
    monkeypatch.setattr("evoagents.tools.os.killpg", lambda pid, sig: events.append(("killpg", pid, sig)))
    with pytest.raises(KeyboardInterrupt):
        runner._git("dev", ["status", "--short"])
    assert events == [("wait", 20), ("killpg", 87654, signal.SIGKILL), ("wait", None)]
