"""OS-enforced execution of untrusted Python in one agent's workspace.

No local subprocess fallback is provided. macOS uses Seatbelt; other hosts
require a working Docker daemon and the local ``python:3.12-slim`` image.
Python starts with ``-I -S`` (standard library and explicit workspace imports).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import sys
import sysconfig
import time
import uuid
from typing import Any


class SandboxUnavailable(RuntimeError):
    """There is no functioning supported isolation backend."""


MAX_TIMEOUT = 120.0
MAX_OUTPUT_BYTES = 64 * 1024
MAX_SCRIPT_BYTES = 2 * 1024 * 1024
DOCKER_IMAGE = "python:3.12-slim"

# This launcher is trusted text supplied on the command line, not a file that
# agent code can replace. Hard resource limits cannot be raised by the script.
_LAUNCHER = """
import os, resource, runpy, sys
cpu = int(sys.argv[2])
limits = [(resource.RLIMIT_CORE, 0), (resource.RLIMIT_CPU, cpu),
          (resource.RLIMIT_FSIZE, 16 * 1024 * 1024),
          (resource.RLIMIT_NOFILE, 64)]
for key, value in limits:
    resource.setrlimit(key, (value, value))
# Linux Docker also supplies a cgroup memory limit. On macOS RLIMIT_AS is not
# a reliable resident-memory bound, so no such guarantee is claimed there.
if sys.platform != 'darwin':
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,) * 2)
script = sys.argv[1]
sys.argv = [script]
sys.path.insert(0, os.getcwd())
runpy.run_path(script, run_name='__main__')
"""


def _safe_environment(workspace: Path) -> dict[str, str]:
    # Do not forward API keys, cloud credentials, PYTHONPATH, LD_PRELOAD, proxy
    # configuration, or the real HOME to untrusted code.
    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(workspace),
        "TMPDIR": str(workspace / ".tmp"),
        "LANG": "en_US.UTF-8",
        "LC_ALL": "en_US.UTF-8",
    }


def _docker_environment() -> dict[str, str]:
    # The trusted Docker CLI needs HOME to locate Docker Desktop's context.
    # This host-only environment is never forwarded into the container.
    return {"PATH": os.defpath, "HOME": str(Path.home())}


def _probe(command: list[str], *, timeout: float = 5) -> tuple[bool, str]:
    try:
        process = subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout, check=False,
            env=_docker_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, type(exc).__name__
    return process.returncode == 0, process.stderr.decode("utf-8", "replace")[:500]


class Sandbox:
    """Execute Python under one private, canonical workspace directory.

    ``backend`` is ``auto``, ``docker``, or ``macos``. ``auto`` prefers a ready
    local Docker image and otherwise uses Seatbelt on macOS. Failure never
    switches to unrestricted execution. Backend availability is checked again
    for each invocation so a stopped daemon cannot produce a false success.
    """

    def __init__(self, workspace: Path, backend: str = "auto") -> None:
        if backend not in {"auto", "docker", "macos"}:
            raise ValueError("sandbox_backend must be auto, docker, or macos")
        original = Path(workspace).absolute()
        if original.is_symlink():
            raise ValueError("Sandbox workspace must not be a symlink")
        original.mkdir(parents=True, exist_ok=True)
        self.workspace = original.resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("Sandbox workspace must be a directory")
        self.backend = backend

    def _docker_ready(self) -> tuple[bool, str]:
        executable = shutil.which("docker")
        if not executable:
            return False, "Docker is not installed"
        ok, _ = _probe([executable, "info", "--format", "{{.ServerVersion}}"])
        if not ok:
            return False, "Docker daemon is unavailable"
        ok, _ = _probe([executable, "image", "inspect", DOCKER_IMAGE])
        if not ok:
            return False, f"Local image is missing; first run docker pull {DOCKER_IMAGE}"
        return True, ""

    def _select_backend(self) -> str:
        if self.backend in {"auto", "docker"}:
            ready, reason = self._docker_ready()
            if ready:
                return "docker"
            if self.backend == "docker":
                raise SandboxUnavailable(reason)
        if self.backend in {"auto", "macos"}:
            if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
                return "macos"
        raise SandboxUnavailable(
            "No supported isolation backend is available. Start Docker and prepare "
            "the python:3.12-slim image, or use sandbox-exec on macOS. "
            "Unrestricted host execution is never used as a fallback."
        )

    def availability(self) -> dict[str, Any]:
        try:
            backend = self._select_backend()
        except SandboxUnavailable as exc:
            return {"available": False, "backend": self.backend, "reason": str(exc)}
        return {
            "available": True,
            "backend": backend,
            "network": False,
            "standard_library_only": True,
            "child_processes": backend == "docker",
            "memory_limit_mb": 512 if backend == "docker" else None,
        }

    def _script(self, path: str) -> Path:
        if not isinstance(path, str) or not path or "\x00" in path:
            raise ValueError("Invalid Python script path")
        relative = Path(path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Script path must stay within the current agent workspace")
        current = self.workspace
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("Script path must not contain symlinks")
        target = current.resolve(strict=True)
        if not target.is_relative_to(self.workspace) or not target.is_file():
            raise ValueError("Script must be a regular file within the workspace")
        if target.suffix.lower() != ".py":
            raise ValueError("Only .py scripts can be executed")
        if target.stat().st_size > MAX_SCRIPT_BYTES:
            raise ValueError("Python script exceeds the 2 MiB size limit")
        return target

    def _mac_profile(self, executable: Path) -> str:
        def literal(path: str | Path) -> str:
            return json.dumps(str(path), ensure_ascii=False)

        # Explicit runtime roots only. In particular, sys.prefix can be the
        # project venv; allowing its parent would expose the project's .env.
        stdlib = Path(sysconfig.get_path("stdlib")).resolve()
        runtime_library = Path(sysconfig.get_config_var("LIBDIR") or executable.parent.parent / "lib")
        dynamic_library = runtime_library / str(sysconfig.get_config_var("LDLIBRARY") or "")
        lines = [
            "(version 1)", "(deny default)",
            f"(allow process-exec (literal {literal(executable)}))",
            "(allow signal (target self))", "(allow sysctl-read)",
            '(allow file-read* (literal "/"))',
            '(allow file-read* (subpath "/System") (subpath "/usr/lib"))',
            f"(allow file-read* (literal {literal(executable)}) (subpath {literal(stdlib)}))",
            f"(allow file-read* (literal {literal(dynamic_library.resolve())}))",
            f"(allow file-read* file-write* (subpath {literal(self.workspace)}))",
            '(allow file-read* file-write* (literal "/dev/null"))',
            '(allow file-read* (literal "/dev/urandom") (literal "/dev/random"))',
        ]
        # No network*, mach-lookup or process-fork allowance. The absence of
        # process-fork prevents detached descendants surviving wall timeout.
        return "\n".join(lines)

    def _docker_command(self, script: Path, timeout: float, name: str) -> list[str]:
        executable = shutil.which("docker")
        if executable is None:
            raise SandboxUnavailable("Docker is not installed")
        if "," in str(self.workspace):
            raise ValueError("Docker workspace path must not contain commas")
        uid = str(os.getuid()) if hasattr(os, "getuid") else "65534"
        gid = str(os.getgid()) if hasattr(os, "getgid") else "65534"
        return [
            executable, "run", "--rm", "--name", name, "--pull=never",
            "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges", "--pids-limit=32",
            "--cpus=1", "--memory=512m", "--memory-swap=512m",
            "--user", f"{uid}:{gid}",
            "--mount", f"type=bind,src={self.workspace},dst=/workspace",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
            "--workdir", "/workspace", "--env", "HOME=/workspace",
            "--env", "TMPDIR=/tmp", "--env", "PYTHONUNBUFFERED=1",
            DOCKER_IMAGE, "python", "-I", "-S", "-u", "-c", _LAUNCHER,
            "/workspace/" + script.relative_to(self.workspace).as_posix(),
            str(max(1, math.ceil(timeout))),
        ]

    def run_python(self, path: str, timeout: float = 30) -> dict[str, Any]:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ValueError("Timeout must be a number")
        if not math.isfinite(timeout) or not 0.1 <= timeout <= MAX_TIMEOUT:
            raise ValueError(f"Timeout must be between 0.1 and {MAX_TIMEOUT:g} seconds")
        script = self._script(path)
        backend = self._select_backend()
        temp = self.workspace / ".tmp"
        if temp.is_symlink():
            raise ValueError("Temporary directory must not be a symlink")
        temp.mkdir(exist_ok=True, mode=0o700)
        name = "evo-agent-" + uuid.uuid4().hex
        if backend == "docker":
            command = self._docker_command(script, float(timeout), name)
        else:
            executable = Path(sys.executable).resolve(strict=True)
            command = [
                "/usr/bin/sandbox-exec", "-p", self._mac_profile(executable),
                str(executable), "-I", "-S", "-u", "-c", _LAUNCHER,
                str(script), str(max(1, math.ceil(timeout))),
            ]
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command, cwd=self.workspace,
                env=_docker_environment() if backend == "docker" else _safe_environment(self.workspace),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True, close_fds=True,
            )
        except OSError as exc:
            raise SandboxUnavailable(f"Unable to start isolation backend: {type(exc).__name__}") from exc
        try:
            stdout, stderr, timed_out, truncated = self._collect(process, float(timeout))
        except BaseException:
            if backend == "docker":
                self._docker_cleanup(command[0], name)
            raise
        if backend == "docker":
            # Killing the docker client alone does not stop a container. Remove
            # this exact random container name after every run, including timeout.
            if not self._docker_cleanup(command[0], name):
                return {
                    "ok": False, "backend": backend, "stdout": stdout,
                    "stderr": stderr, "exit_code": process.returncode,
                    "timed_out": timed_out, "output_truncated": truncated,
                    "error": "Docker cleanup failed; inspect and remove container " + name,
                }
        return {
            "ok": process.returncode == 0 and not timed_out,
            "backend": backend, "stdout": stdout, "stderr": stderr,
            "exit_code": process.returncode, "timed_out": timed_out,
            "output_truncated": truncated,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }

    @staticmethod
    def _docker_cleanup(executable: str, name: str) -> bool:
        try:
            result = subprocess.run(
                [executable, "rm", "-f", name], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                timeout=10, check=False, env=_docker_environment(),
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        # --rm usually removed an exited container already. Other errors such
        # as a disconnected daemon must be surfaced, not reported as cleanup.
        return result.returncode == 0 or b"No such container:" in result.stderr

    @staticmethod
    def _collect(process: subprocess.Popen[bytes], timeout: float) -> tuple[str, str, bool, bool]:
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        truncated = False
        timed_out = False
        deadline = time.monotonic() + timeout
        selector = selectors.DefaultSelector()
        for key in buffers:
            pipe = getattr(process, key)
            assert pipe is not None
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, key)
        try:
            while selector.get_map() or process.poll() is None:
                if time.monotonic() >= deadline:
                    timed_out = True
                    break
                for event, _ in selector.select(timeout=min(0.05, max(0, deadline - time.monotonic()))):
                    chunk = os.read(event.fileobj.fileno(), 8192)
                    if not chunk:
                        selector.unregister(event.fileobj)
                        continue
                    buffer = buffers[event.data]
                    remaining = MAX_OUTPUT_BYTES - len(buffer)
                    buffer.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        truncated = True
            if timed_out or process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=5)
        finally:
            selector.close()
            for pipe in (process.stdout, process.stderr):
                if pipe is not None:
                    pipe.close()
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)
        return (
            buffers["stdout"].decode("utf-8", "replace"),
            buffers["stderr"].decode("utf-8", "replace"), timed_out, truncated,
        )
