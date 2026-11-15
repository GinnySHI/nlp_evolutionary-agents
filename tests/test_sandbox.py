from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time

import pytest

from evoagents.sandbox import MAX_OUTPUT_BYTES, Sandbox, SandboxUnavailable


@pytest.fixture
def sandbox(tmp_path):
    if sys.platform != "darwin" or not Path("/usr/bin/sandbox-exec").exists():
        pytest.skip("macOS Seatbelt integration tests require sandbox-exec")
    return Sandbox(tmp_path / "agent" / "workspace", backend="macos")


def run_script(sandbox, source, timeout=10):
    (sandbox.workspace / "main.py").write_text(source, encoding="utf-8")
    return sandbox.run_python("main.py", timeout=timeout)


def test_python_can_read_write_own_workspace(sandbox):
    result = run_script(sandbox, "from pathlib import Path\nimport json\np=Path('answer.txt'); p.write_text('42'); print(json.dumps({'answer':p.read_text()}))")
    assert result["ok"], result
    assert json.loads(result["stdout"]) == {"answer": "42"}
    assert (sandbox.workspace / "answer.txt").read_text() == "42"


def test_other_workspace_host_secret_and_environment_are_denied(sandbox, tmp_path, monkeypatch):
    outside = tmp_path / "other-agent" / "secret.txt"
    outside.parent.mkdir()
    outside.write_text("private-peer-data")
    monkeypatch.setenv("HKGAI_API_KEY", "sensitive-test-value")
    source = f"""import os
from pathlib import Path
assert 'HKGAI_API_KEY' not in os.environ
assert os.environ['HOME'] == os.getcwd()
try:
    Path({str(outside)!r}).read_text()
except PermissionError:
    print('read-blocked')
else:
    raise RuntimeError('private data leaked')
try:
    Path({str(outside)!r}).write_text('changed')
except PermissionError:
    print('write-blocked')
else:
    raise RuntimeError('private data overwritten')
"""
    result = run_script(sandbox, source)
    assert result["ok"], result
    assert "read-blocked" in result["stdout"]
    assert "write-blocked" in result["stdout"]
    assert outside.read_text() == "private-peer-data"


def test_network_and_child_process_creation_denied(sandbox):
    source = """import socket, os, sys, subprocess
try:
    s=socket.socket(); s.connect(('127.0.0.1', 80))
except PermissionError:
    print('network-blocked')
else:
    raise RuntimeError('network unexpectedly permitted')
try:
    pid=os.fork()
except PermissionError:
    print('fork-blocked')
else:
    if pid == 0: os._exit(99)
    raise RuntimeError('fork unexpectedly permitted')
try:
    subprocess.run([sys.executable, '-I', '-S', '-c', 'print(99)'], check=True)
except PermissionError:
    print('spawn-blocked')
else:
    raise RuntimeError('spawn unexpectedly permitted')
"""
    result = run_script(sandbox, source)
    assert result["ok"], result
    assert "network-blocked" in result["stdout"]
    assert "fork-blocked" in result["stdout"]
    assert "spawn-blocked" in result["stdout"]


def test_wall_timeout_kills_execution_and_no_detached_children(sandbox):
    started = time.monotonic()
    result = run_script(sandbox, "import time\nwhile True: time.sleep(0.05)", timeout=0.3)
    assert result["timed_out"]
    assert not result["ok"]
    assert time.monotonic() - started < 5


def test_output_is_bounded(sandbox):
    result = run_script(sandbox, "print('a' * 200000)")
    assert result["ok"], result
    assert result["output_truncated"]
    assert len(result["stdout"].encode()) == MAX_OUTPUT_BYTES


def test_hard_file_size_limit(sandbox):
    source = """from pathlib import Path
try:
    Path('too-big.txt').write_bytes(b'a' * (20 * 1024 * 1024))
except OSError:
    print('size-blocked')
else:
    raise RuntimeError('file size limit not applied')
"""
    result = run_script(sandbox, source)
    assert result["ok"], result
    assert "size-blocked" in result["stdout"]
    assert (sandbox.workspace / "too-big.txt").stat().st_size <= 16 * 1024 * 1024


@pytest.mark.parametrize("path", ["../escape.py", "/tmp/escape.py", "bad.txt", "bad\x00.py"])
def test_invalid_script_paths_rejected(tmp_path, path):
    box = Sandbox(tmp_path)
    (tmp_path / "bad.txt").write_text("pass")
    with pytest.raises((ValueError, FileNotFoundError)):
        box.run_python(path)


def test_symlink_script_rejected(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.py")
    outside.write_text("pass")
    (tmp_path / "linked.py").symlink_to(outside)
    with pytest.raises(ValueError, match="symlink"):
        Sandbox(tmp_path).run_python("linked.py")


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 121, True, "30"])
def test_invalid_timeout_rejected(tmp_path, timeout):
    with pytest.raises(ValueError):
        Sandbox(tmp_path).run_python("main.py", timeout)


def test_unavailable_backend_never_executes_host_code(tmp_path, monkeypatch):
    from evoagents import sandbox as module
    monkeypatch.setattr(module.sys, "platform", "linux")
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    (tmp_path / "main.py").write_text("open('UNSAFE.txt','w').write('executed')")
    box = Sandbox(tmp_path)
    assert box.availability()["available"] is False
    with pytest.raises(SandboxUnavailable):
        box.run_python("main.py")
    assert not (tmp_path / "UNSAFE.txt").exists()


def test_docker_command_has_required_isolation_flags(tmp_path, monkeypatch):
    from evoagents import sandbox as module
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker")
    box = Sandbox(tmp_path, backend="docker")
    script = tmp_path / "main.py"
    script.write_text("pass")
    command = box._docker_command(script, 10, "test-name")
    for flag in ["--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--pids-limit=32", "--memory=512m", "--pull=never"]:
        assert flag in command
    assert not any("docker.sock" in token or token == "--privileged" for token in command)
    assert command.count("--mount") == 1


def test_docker_service_failure_is_clear(tmp_path, monkeypatch):
    from evoagents import sandbox as module
    monkeypatch.setattr(module.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(module, "_probe", lambda command: (False, "service unavailable"))
    (tmp_path / "main.py").write_text("pass")
    with pytest.raises(SandboxUnavailable, match="daemon"):
        Sandbox(tmp_path, backend="docker").run_python("main.py")


def test_docker_cleanup_distinguishes_removed_from_daemon_failure(monkeypatch):
    from evoagents import sandbox as module
    def response(stderr):
        return module.subprocess.CompletedProcess([], 1, b"", stderr)
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: response(b"Error response from daemon: No such container: example"))
    assert Sandbox._docker_cleanup("docker", "example")
    monkeypatch.setattr(module.subprocess, "run", lambda *args, **kwargs: response(b"Cannot connect to the Docker daemon"))
    assert not Sandbox._docker_cleanup("docker", "example")
