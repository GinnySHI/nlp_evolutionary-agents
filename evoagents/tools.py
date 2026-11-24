"""Bounded external tools with explicit approvals and per-agent file boundaries.

Remote text is untrusted evidence, never an instruction. HTTP requests connect to
a validated, pinned public IP so a second DNS lookup cannot rebind to localhost.
Untrusted Python is delegated exclusively to the OS/container sandbox.
"""

from __future__ import annotations

import base64
import configparser
import contextlib
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import socket
import stat
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree
from html.parser import HTMLParser

import httpx

from .sandbox import Sandbox
from .validation import validate_text


MAX_FILE_BYTES = 512 * 1024
MAX_APPEND_BYTES = 32 * 1024
MAX_OUTPUT_CHARS = 64000
MAX_WEB_BYTES = 512 * 1024
AGENT_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
TEXT_SUFFIXES = {
    ".md", ".txt", ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".css", ".html", ".htm", ".json", ".jsonl", ".toml", ".yaml", ".yml",
    ".ini", ".cfg", ".sql", ".xml", ".svg", ".sh", ".c", ".h", ".cpp",
    ".rs", ".go", ".java",
}
TEXT_FILENAMES = {"README", "LICENSE", "Makefile", "Dockerfile", ".gitignore", ".dockerignore", ".env.example"}
CRITICAL_TOOLS = frozenset({"delete_file", "run_python", "git_commit", "git_push"})


class ToolError(ValueError):
    """A rejected request with a safe user-facing explanation."""


def _spec(name: str, description: str, properties: dict, required: list[str] = ()) -> dict:
    return {"name": name, "description": description,
            "parameters": {"type": "object", "properties": properties,
                           "required": list(required), "additionalProperties": False},
            "requires_approval": name in CRITICAL_TOOLS}


STRING = {"type": "string"}
SPECS = [
    _spec("list_files", "List your own workspace files (up to 1000).", {"path": STRING}),
    _spec("read_file", "Read UTF-8 text/code with full-file SHA256. Use offset/limit (character positions) to inspect later sections; next_offset continues a truncated read. Documents must be .md or .txt.", {"path": STRING, "offset": {"type": "integer", "minimum": 0, "maximum": MAX_FILE_BYTES}, "limit": {"type": "integer", "minimum": 1, "maximum": MAX_OUTPUT_CHARS}}, ["path"]),
    _spec("validate_file", "Read-only static syntax/structure check for Python, JSON or complete HTML. Detects duplicate HTML documents/IDs and date-conversion risks. Never executes scripts; not a functional test. Fix errors before sharing.", {"path": STRING}, ["path"]),
    _spec("write_file", "Create or replace a UTF-8 text/code file (max 512 KiB). For long files, write a small first chunk, then append_file using the returned sha256; keep each response short.", {"path": STRING, "content": STRING}, ["path", "content"]),
    _spec("append_file", "Append a UTF-8 chunk of at most 32 KiB to an existing file only if expected_sha256 matches its current full contents. Use the sha256 from write_file/read_file/append_file. A repeated stale request is rejected, never appended twice. Maximum total size 512 KiB.", {"path": STRING, "content": STRING, "expected_sha256": STRING}, ["path", "content", "expected_sha256"]),
    _spec("replace_text", "Replace one exact, unique nonempty text span in a file, with current full-file expected_sha256. old/new are at most 32 KiB each. Read the relevant section first; ambiguous or stale edits fail. Prefer this to rewriting a large file for a small correction.", {"path": STRING, "old": STRING, "new": STRING, "expected_sha256": STRING}, ["path", "old", "new", "expected_sha256"]),
    _spec("delete_file", "Delete one file. Requires explicit human approval.", {"path": STRING}, ["path"]),
    _spec("run_python", "Run a workspace .py file with Python standard library and workspace imports only. No network, stdin, package installation, or persistent servers. macOS forbids subprocess/process creation: test by importing modules and calling functions in the same process. Requires human approval.", {"path": STRING, "timeout": {"type": "number", "minimum": 1, "maximum": 120}}, ["path"]),
    _spec("search_web", "Search public web pages via Bing RSS. Inspect result relevance; a successful HTTP response is not proof of useful evidence. If relevance_warning is present, change query or fetch a known primary source.", {"query": STRING, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ["query"]),
    _spec("fetch_url", "Fetch a public HTTP(S) text page with DNS/IP and redirect validation. HTML includes discovered links; follow relevant links instead of guessing article URLs. No private network access.", {"url": STRING}, ["url"]),
    _spec("send_file", "Copy one file to recipient's inbox/<sender>/<destination>. Never overwrites existing files. Share only intended files.", {"recipient": STRING, "path": STRING, "destination": STRING}, ["recipient", "path", "destination"]),
    _spec("git_init", "Initialize a private workspace Git repository.", {}),
    _spec("git_status", "Read workspace Git status; hooks and external configuration are disabled.", {}),
    _spec("git_diff", "Read unstaged and staged differences without external diff/text conversion.", {}),
    _spec("git_commit", "Stage workspace files and create a commit, using the agent identity. Requires human approval.", {"message": STRING}, ["message"]),
    _spec("git_push", "Push HEAD to an explicit branch of an HTTPS github.com repository. Requires human approval and optional host EVO_GITHUB_TOKEN.", {"remote_url": STRING, "branch": STRING}, ["remote_url", "branch"]),
]
SPEC_BY_NAME = {s["name"]: s for s in SPECS}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in {"script", "style", "noscript", "svg", "head"}:
            self.hidden += 1
        elif tag in {"p", "br", "div", "li", "h1", "h2", "h3", "tr", "section"} and not self.hidden:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "head"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _plain_html(value: str) -> str:
    parser = _TextExtractor()
    parser.feed(value)
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


class _LinkExtractor(HTMLParser):
    def __init__(self, base: str):
        super().__init__()
        self.base, self.links, self.current = base, [], None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            url = urljoin(self.base, href)
            parsed = urlsplit(url)
            if (href and not href.startswith("#") and parsed.scheme in {"http", "https"}
                    and parsed.hostname and not parsed.username and not parsed.password and len(url) <= 4096):
                self.current = {"url": url, "text": ""}

    def handle_data(self, data):
        if self.current is not None:
            self.current["text"] += data[:300]

    def handle_endtag(self, tag):
        if tag == "a" and self.current is not None:
            self.current["text"] = " ".join(self.current["text"].split())[:300]
            if len(self.links) < 80 and self.current["text"] and self.current not in self.links:
                self.links.append(self.current)
            self.current = None


def _is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        return _is_public(str(ip.ipv4_mapped))
    return ip.is_global and not (ip.is_multicast or ip.is_reserved or ip.is_unspecified)


def _public_target(url: str) -> tuple[str, str, str]:
    """Return (pinned URL, Host header, TLS hostname) after checking ALL DNS answers."""
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 for c in url):
        raise ToolError("Invalid or oversized URL.")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ToolError("Only credential-free public HTTP(S) URLs are allowed.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        host = parsed.hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError) as exc:
        raise ToolError("Invalid URL hostname or port.") from exc
    if port not in {80, 443} or "%" in host or "\\" in host:
        raise ToolError("Only public web ports 80 and 443 are allowed.")
    try:
        addresses = sorted({r[4][0] for r in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}, key=lambda a: (":" in a, a))
    except OSError as exc:
        raise ToolError("Unable to resolve the website hostname.") from exc
    if not addresses or any(not _is_public(address) for address in addresses):
        raise ToolError("Private, loopback, link-local, reserved and mixed public/private destinations are blocked.")
    address = addresses[0]
    target_host = f"[{address}]" if ":" in address else address
    authority = f"{target_host}:{port}"
    host_header = (f"[{host}]" if ":" in host else host) + (f":{port}" if port != (443 if parsed.scheme == "https" else 80) else "")
    pinned = urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))
    return pinned, host_header, host


class ToolRunner:
    def __init__(self, workspace_root: Path, *, agent_ids: list[str], sandbox_backend: str = "auto", http_timeout: float = 20):
        if not agent_ids or len(set(agent_ids)) != len(agent_ids) or any(not AGENT_ID.fullmatch(a) for a in agent_ids):
            raise ToolError("Agent IDs must be unique simple identifiers beginning with a letter.")
        root = Path(workspace_root).absolute()
        if root.is_symlink():
            raise ToolError("Workspace root cannot be a symlink.")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = root.resolve()
        self.agent_ids = frozenset(agent_ids)
        self.sandbox_backend = sandbox_backend
        self.http_timeout = max(1, min(float(http_timeout), 60))
        for agent_id in agent_ids:
            self.workspace(agent_id)

    def workspace(self, agent_id: str) -> Path:
        if agent_id not in self.agent_ids:
            raise ToolError("Unknown agent.")
        parent = self.root / agent_id
        workspace = parent / "workspace"
        for directory in (parent, workspace):
            if directory.is_symlink():
                raise ToolError("Agent directories cannot be symlinks.")
            directory.mkdir(exist_ok=True, mode=0o700)
        return workspace

    @staticmethod
    def specifications() -> list[dict]:
        return json.loads(json.dumps(SPECS))

    @staticmethod
    def requires_approval(name: str) -> bool:
        return name in CRITICAL_TOOLS

    @staticmethod
    def _parts(path: str, *, directory: bool = False) -> tuple[str, ...]:
        if not isinstance(path, str) or not path or len(path) > 1024 or "\\" in path or "\x00" in path or ":" in path:
            raise ToolError("A bounded workspace-relative path is required.")
        raw = path.split("/")
        if path.startswith("/") or ".." in raw or ".git" in raw or any(part.startswith(".tool-") for part in raw):
            raise ToolError("Absolute paths, parent traversal and Git internals are not accessible.")
        parts = tuple(part for part in raw if part not in {"", "."})
        if len(parts) > 32 or (not parts and not directory):
            raise ToolError("Invalid workspace path.")
        if not directory:
            filename = parts[-1]
            if filename not in TEXT_FILENAMES and PurePosixPath(filename).suffix.lower() not in TEXT_SUFFIXES:
                raise ToolError("Unsupported file format. Use .md/.txt for documents or a supported code/config extension.")
        return parts

    @contextlib.contextmanager
    def _parent_fd(self, agent_id: str, path: str, *, create: bool = False):
        parts = self._parts(path)
        fd = os.open(self.workspace(agent_id), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                if create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd
            yield fd, parts[-1]
        finally:
            os.close(fd)

    def _read(self, agent_id: str, path: str) -> bytes:
        with self._parent_fd(agent_id, path) as (parent_fd, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES:
                    raise ToolError("Only regular, unlinked UTF-8 files up to 512 KiB can be read.")
                content = stream.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise ToolError("File exceeds 512 KiB limit.")
        content.decode("utf-8")
        return content

    def _write(self, agent_id: str, path: str, data: bytes, *, exclusive: bool = False,
               expected_sha256: str | None = None, replace_old: bytes | None = None) -> bytes:
        if len(data) > MAX_FILE_BYTES:
            raise ToolError("File exceeds 512 KiB limit.")
        with self._parent_fd(agent_id, path, create=True) as (parent_fd, name):
            try:
                current = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                current = None
            if current is not None and (exclusive or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1):
                raise ToolError("Destination exists or is not a regular isolated file.")
            if expected_sha256 is not None:
                if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
                    raise ToolError("expected_sha256 must be a lowercase SHA256 from the previous file result.")
                if current is None:
                    raise ToolError("Edit target does not exist; use write_file first.")
                source_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent_fd)
                with os.fdopen(source_fd, "rb") as source:
                    source_info = os.fstat(source.fileno())
                    if (not stat.S_ISREG(source_info.st_mode) or source_info.st_nlink != 1 or
                            source_info.st_size > MAX_FILE_BYTES):
                        raise ToolError("Edit target must be a regular isolated file up to 512 KiB.")
                    previous = source.read(MAX_FILE_BYTES + 1)
                previous.decode("utf-8")
                if hashlib.sha256(previous).hexdigest() != expected_sha256:
                    raise ToolError("Edit precondition failed: the file changed. Read it again before editing.")
                if replace_old is None:
                    data = previous + data
                else:
                    if (not replace_old or previous.find(replace_old) < 0 or
                            previous.find(replace_old) != previous.rfind(replace_old)):
                        raise ToolError("old must match exactly one nonempty span; read the file and provide a unique context.")
                    data = previous.replace(replace_old, data, 1)
                if len(data) > MAX_FILE_BYTES:
                    raise ToolError("File exceeds 512 KiB limit.")
                current = source_info
            temporary = f".tool-{os.urandom(12).hex()}.tmp"
            fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if exclusive:
                    # A hard link publishes atomically without clobbering a racing destination.
                    os.link(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
                else:
                    if expected_sha256 is not None:
                        latest = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                        if ((latest.st_dev, latest.st_ino, latest.st_size, latest.st_mtime_ns, latest.st_ctime_ns) !=
                                (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns, current.st_ctime_ns)):
                            raise ToolError("Edit target changed during the operation; no change was written.")
                    os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=parent_fd)
                except FileNotFoundError:
                    pass
        return data

    @staticmethod
    def _file_result(path: str, data: bytes, **extra) -> dict:
        result = {"ok": True, "path": path, "bytes": len(data),
                  "sha256": hashlib.sha256(data).hexdigest(), **extra}
        if len(data) > 200 and b"\n" not in data and data.count(b"\\n") >= 5:
            result["warning"] = ("File contains many literal backslash-n sequences and no actual newline. "
                                 "If unintended, correct the JSON string escaping. Bytes were saved unchanged.")
        return result

    def _list(self, agent_id: str, path: str) -> dict:
        parts = self._parts(path, directory=True)
        fd = os.open(self.workspace(agent_id), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        entries: list[dict] = []
        try:
            for part in parts:
                next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = next_fd

            def visit(directory_fd: int, prefix: str, depth: int = 0) -> None:
                if depth > 32:
                    raise ToolError("Directory nesting exceeds limit.")
                with os.scandir(directory_fd) as children:
                    for entry in sorted(children, key=lambda e: e.name):
                        if entry.name == ".git" or entry.name.startswith(".tool-"):
                            continue
                        if len(entries) >= 1000:
                            return
                        if entry.is_symlink():
                            raise ToolError("Symlinks are not permitted inside workspaces.")
                        relative = f"{prefix}/{entry.name}" if prefix else entry.name
                        info = entry.stat(follow_symlinks=False)
                        if stat.S_ISDIR(info.st_mode):
                            child_fd = os.open(entry.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
                            try:
                                visit(child_fd, relative, depth + 1)
                            finally:
                                os.close(child_fd)
                        elif stat.S_ISREG(info.st_mode):
                            entries.append({"path": relative, "bytes": info.st_size})
            visit(fd, "/".join(parts))
        finally:
            os.close(fd)
        return {"ok": True, "files": entries, "truncated": len(entries) >= 1000}

    @staticmethod
    def _validate_arguments(name: str, arguments: dict) -> None:
        if name not in SPEC_BY_NAME:
            raise ToolError("Unknown tool.")
        if not isinstance(arguments, dict):
            raise ToolError("Tool arguments must be a JSON object.")
        schema = SPEC_BY_NAME[name]["parameters"]
        if set(arguments) - set(schema["properties"]):
            raise ToolError("Unexpected tool arguments.")
        if set(schema["required"]) - set(arguments):
            raise ToolError("Missing required tool arguments.")
        for key, value in arguments.items():
            expected = schema["properties"][key]
            kind = expected["type"]
            valid = (isinstance(value, str) if kind == "string" else
                     isinstance(value, int) and not isinstance(value, bool) if kind == "integer" else
                     isinstance(value, (int, float)) and not isinstance(value, bool))
            if not valid or (kind != "string" and not expected["minimum"] <= value <= expected["maximum"]):
                raise ToolError(f"Invalid value for {key}.")

    def execute(self, agent_id: str, name: str, arguments: dict, *, approved: bool = False) -> dict:
        try:
            self.workspace(agent_id)
            self._validate_arguments(name, arguments)
            if self.requires_approval(name) and approved is not True:
                return {"ok": False, "error": "Explicit human approval is required for this exact operation.", "approval_required": True}
            if name == "read_file":
                data = self._read(agent_id, arguments["path"])
                text = data.decode("utf-8")
                offset = arguments.get("offset", 0)
                end = min(len(text), offset + arguments.get("limit", MAX_OUTPUT_CHARS))
                excerpt = text[offset:end]
                result = self._file_result(arguments["path"], data, offset=offset,
                                           total_chars=len(text), next_offset=end if end < len(text) else None,
                                           truncated=offset > 0 or end < len(text))
                result["content"] = excerpt
                return result
            if name == "validate_file":
                data = self._read(agent_id, arguments["path"])
                return self._file_result(arguments["path"], data,
                                         **validate_text(arguments["path"], data.decode("utf-8")))
            if name == "write_file":
                data = arguments["content"].encode("utf-8")
                self._write(agent_id, arguments["path"], data)
                return self._file_result(arguments["path"], data)
            if name == "append_file":
                chunk = arguments["content"].encode("utf-8")
                if not chunk or len(chunk) > MAX_APPEND_BYTES:
                    raise ToolError("Append content must contain between 1 byte and 32 KiB of UTF-8 text.")
                data = self._write(agent_id, arguments["path"], chunk, expected_sha256=arguments["expected_sha256"])
                return self._file_result(arguments["path"], data, appended_bytes=len(chunk))
            if name == "replace_text":
                old, new = arguments["old"].encode("utf-8"), arguments["new"].encode("utf-8")
                if not old or max(len(old), len(new)) > MAX_APPEND_BYTES:
                    raise ToolError("old must be nonempty; old and new must each be at most 32 KiB.")
                data = self._write(agent_id, arguments["path"], new,
                                   expected_sha256=arguments["expected_sha256"], replace_old=old)
                return self._file_result(arguments["path"], data, replacements=1)
            if name == "list_files":
                return self._list(agent_id, arguments.get("path", "."))
            if name == "delete_file":
                with self._parent_fd(agent_id, arguments["path"]) as (fd, filename):
                    info = os.stat(filename, dir_fd=fd, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                        raise ToolError("Only regular isolated files may be deleted.")
                    os.unlink(filename, dir_fd=fd)
                return {"ok": True, "deleted": arguments["path"]}
            if name == "run_python":
                self._parts(arguments["path"])
                if PurePosixPath(arguments["path"]).suffix.lower() != ".py":
                    raise ToolError("run_python requires a .py file.")
                return Sandbox(self.workspace(agent_id), backend=self.sandbox_backend).run_python(arguments["path"], timeout=arguments.get("timeout", 30))
            if name == "send_file":
                return self._send(agent_id, **arguments)
            if name == "fetch_url":
                result = self._http_fetch(arguments["url"])
                html = "html" in result["content_type"].lower()
                content = _plain_html(result["content"]) if html else result["content"]
                links = _LinkExtractor(result.get("url", arguments["url"]))
                if html:
                    links.feed(result["content"])
                metadata = {key: value for key, value in result.items() if key != "content"}
                return {**metadata, "links": links.links, "content": content[:MAX_OUTPUT_CHARS],
                        "truncated": result["truncated"] or len(content) > MAX_OUTPUT_CHARS}
            if name == "search_web":
                return self._search(arguments["query"], arguments.get("limit", 5))
            if name.startswith("git_"):
                return self._git_tool(agent_id, name, arguments)
            raise ToolError("Unknown tool.")
        except Exception as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            message = str(exc)
            for key in ("HKGAI_API_KEY", "DEEPSEEK_API_KEY", "EVO_GITHUB_TOKEN", "API_KEY"):
                secret = os.environ.get(key)
                if secret:
                    message = message.replace(secret, "[REDACTED]")
            return {"ok": False, "error": message[:1000] or type(exc).__name__, "error_type": type(exc).__name__}

    def _send(self, agent_id: str, recipient: str, path: str, destination: str) -> dict:
        self.workspace(recipient)
        if agent_id == recipient:
            raise ToolError("Choose a different recipient.")
        # send_file owns the inbox/<sender>/ prefix. If the caller already
        # supplied that exact prefix (a common handoff-path mistake), strip it
        # once so transfers do not land in inbox/<sender>/inbox/<sender>/... .
        canonical_destination = destination
        owned_prefix = f"inbox/{agent_id}/"
        if canonical_destination.startswith(owned_prefix):
            canonical_destination = canonical_destination[len(owned_prefix):]
        self._parts(canonical_destination)
        data = self._read(agent_id, path)
        target = f"inbox/{agent_id}/{canonical_destination}"
        self._write(recipient, target, data, exclusive=True)
        receipt = {"sender": agent_id, "recipient": recipient, "source": path, "destination": target,
                   "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "timestamp": time.time()}
        log = self.root / "transfers.jsonl"
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(receipt, ensure_ascii=False) + "\n")
        return {"ok": True, **receipt}

    def _http_fetch(self, url: str) -> dict:
        current = url
        deadline = time.monotonic() + self.http_timeout
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=self.http_timeout) as client:
            for hop in range(6):
                pinned, host_header, tls_hostname = _public_target(current)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ToolError("Web retrieval exceeded its time limit.")
                with client.stream("GET", pinned,
                                   headers={"Host": host_header, "User-Agent": "EvoAgentsResearch/1.0", "Accept-Encoding": "identity"},
                                   extensions={"sni_hostname": tls_hostname}, timeout=remaining) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        target = response.headers.get("location")
                        if not target or hop == 5:
                            raise ToolError("Too many redirects or missing redirect destination.")
                        current = urljoin(current, target)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if not (content_type.startswith("text/") or content_type in {"application/json", "application/xml", "application/rss+xml", "application/xhtml+xml"}):
                        raise ToolError("The URL is not a supported text page. PDF, Office documents and binary downloads are unsupported.")
                    if response.headers.get("content-encoding", "identity").lower() not in {"identity", ""}:
                        raise ToolError("Compressed responses are unsupported; the website must honor Accept-Encoding: identity.")
                    chunks, size, truncated = [], 0, False
                    for chunk in response.iter_bytes():
                        if time.monotonic() > deadline:
                            raise ToolError("Web retrieval exceeded its time limit.")
                        if size + len(chunk) > MAX_WEB_BYTES:
                            chunks.append(chunk[:MAX_WEB_BYTES-size])
                            truncated = True
                            break
                        chunks.append(chunk)
                        size += len(chunk)
                    content = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
                    return {"ok": True, "url": current, "content_type": content_type, "content": content,
                            "truncated": truncated, "untrusted": True, "retrieved_at": time.time()}
        raise ToolError("Unable to retrieve public webpage.")

    def _search(self, query: str, limit: int) -> dict:
        if not query.strip() or len(query) > 1000:
            raise ToolError("Search query must contain between 1 and 1000 characters.")
        source = "https://www.bing.com/search?format=rss&q=" + quote(query)
        page = self._http_fetch(source)
        if page["truncated"]:
            raise ToolError("Search response exceeded the size limit.")
        try:
            root = ElementTree.fromstring(page["content"])
        except ElementTree.ParseError as exc:
            raise ToolError("Search service did not return RSS. Try fetch_url with a known public source.") from exc
        results = []
        for item in root.findall(".//item"):
            url = item.findtext("link", "")
            if urlsplit(url).scheme not in {"http", "https"}:
                continue
            results.append({"title": _plain_html(item.findtext("title", ""))[:500], "url": url,
                            "snippet": _plain_html(item.findtext("description", ""))[:2000]})
            if len(results) >= limit:
                break
        # Do not silently discard potentially useful results. Surface a lexical
        # warning instead: HTTP success alone can conceal irrelevant search hits.
        # This is only a hint, not semantic validation of the cited evidence.
        terms = {word for word in re.findall(r"[a-z][a-z0-9-]{2,}", query.lower())
                 if word not in {"the", "and", "for", "with", "from", "that", "this", "site", "www", "com", "org"}}
        ranked_results = []
        for result in results:
            haystack = " ".join(result.values()).lower()
            matched = sorted(term for term in terms if term in haystack)
            ranked_results.append({**result, "matched_query_terms": matched})
        warning = None
        if not results:
            warning = "No search results. Try a more specific query or fetch_url with a known primary source."
        elif len(terms) >= 3 and all(len(item["matched_query_terms"]) / len(terms) < 0.35 for item in ranked_results):
            warning = ("Search results have little lexical overlap with the query and may be irrelevant. "
                       "Do not cite them without checking; change the query or fetch a known primary source.")
        return {"ok": True, "query": query, "results": ranked_results, "source_url": source, "untrusted": True,
                "relevance_warning": warning, "retrieved_at": page["retrieved_at"]}

    @staticmethod
    def _git_environment(agent_id: str, token: str | None = None) -> dict[str, str]:
        env = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "LANG": "C", "LC_ALL": "C",
               "HOME": "/nonexistent", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
               "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/usr/bin/false",
               "GIT_AUTHOR_NAME": f"EvoAgents {agent_id}", "GIT_AUTHOR_EMAIL": f"{agent_id}@agents.invalid",
               "GIT_COMMITTER_NAME": f"EvoAgents {agent_id}", "GIT_COMMITTER_EMAIL": f"{agent_id}@agents.invalid"}
        overrides = [("core.hooksPath", os.devnull), ("core.fsmonitor", "false"), ("credential.helper", ""),
                     ("protocol.allow", "never"), ("protocol.https.allow", "always"),
                     ("http.followRedirects", "false"), ("commit.gpgsign", "false"),
                     ("core.sshCommand", "/usr/bin/false")]
        if token:
            authorization = base64.b64encode(("x-access-token:" + token).encode()).decode()
            overrides.append(("http.https://github.com/.extraheader", "Authorization: Basic " + authorization))
        env["GIT_CONFIG_COUNT"] = str(len(overrides))
        for index, (key, value) in enumerate(overrides):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        return env

    def _git(self, agent_id: str, args: list[str], *, token: str | None = None, timeout: float = 20) -> dict:
        executable = shutil.which("git")
        if not executable:
            raise ToolError("Git is not installed.")
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            process = subprocess.Popen([executable, "--no-pager", *args], cwd=self.workspace(agent_id),
                                       env=self._git_environment(agent_id, token), stdin=subprocess.DEVNULL,
                                       stdout=output, stderr=error, start_new_session=True)
            timed_out = False
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                code = process.wait()
            except BaseException:
                # An interrupted approved push must not keep running after the
                # CLI returns. Its remote outcome can still be uncertain, so
                # propagate the interrupt for the engine's reconciliation path.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                raise
            output.seek(0)
            error.seek(0)
            stdout = output.read(MAX_OUTPUT_CHARS + 1).decode("utf-8", errors="replace")
            stderr = error.read(MAX_OUTPUT_CHARS + 1).decode("utf-8", errors="replace")
        if token:
            encoded = base64.b64encode(("x-access-token:" + token).encode()).decode()
            stdout = stdout.replace(token, "[REDACTED]").replace(encoded, "[REDACTED]")
            stderr = stderr.replace(token, "[REDACTED]").replace(encoded, "[REDACTED]")
        return {"ok": code == 0 and not timed_out, "exit_code": code, "stdout": stdout[:MAX_OUTPUT_CHARS],
                "stderr": stderr[:MAX_OUTPUT_CHARS], "timed_out": timed_out,
                "truncated": len(stdout) > MAX_OUTPUT_CHARS or len(stderr) > MAX_OUTPUT_CHARS}

    def _validate_repository(self, agent_id: str) -> None:
        workspace = self.workspace(agent_id)
        repository = workspace / ".git"
        if repository.is_symlink() or not repository.is_dir():
            raise ToolError("Initialize a normal workspace Git repository first.")
        count = 0
        for directory, dirs, files in os.walk(repository, followlinks=False):
            for filename in dirs + files:
                path = Path(directory) / filename
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode) or (not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1)):
                    raise ToolError("Git internals must not contain symlinks, special files or hard links.")
                count += 1
                if count > 20000:
                    raise ToolError("Git repository exceeds the inspection limit.")
        for filename in ("commondir", "objects/info/alternates", "objects/info/http-alternates", "config.worktree"):
            if (repository / filename).exists():
                raise ToolError("External Git object stores and linked worktrees are unsupported.")
        if (repository / "config").stat().st_size > 16384:
            raise ToolError("Git config exceeds limit.")
        # Parse once before invoking Git; includes are rejected before they can be read.
        config = configparser.ConfigParser(strict=True, interpolation=None)
        config.read_string((repository / "config").read_text(encoding="utf-8"))
        allowed = {"core": {"repositoryformatversion", "filemode", "bare", "logallrefupdates", "ignorecase", "precomposeunicode"},
                   "user": {"name", "email"}}
        if config.defaults() or any(section.lower() not in allowed or set(config[section]) - allowed[section.lower()] for section in config.sections()):
            raise ToolError("Unsupported Git configuration. Includes, aliases, filters, helpers and custom hooks are not allowed.")
        actual = self._git(agent_id, ["config", "--local", "--no-includes", "--null", "--list"])
        if not actual["ok"] or actual["truncated"]:
            raise ToolError("Unable to validate repository configuration.")
        allowed_keys = {f"{section}.{key}" for section, keys in allowed.items() for key in keys}
        for entry in actual["stdout"].split("\0"):
            if entry and entry.split("\n", 1)[0].lower() not in allowed_keys:
                raise ToolError("Unsupported Git configuration key.")

    def _git_tool(self, agent_id: str, name: str, arguments: dict) -> dict:
        repository = self.workspace(agent_id) / ".git"
        if name == "git_init":
            if repository.exists() or repository.is_symlink():
                self._validate_repository(agent_id)
                return {"ok": True, "message": "Repository already initialized."}
            return self._git(agent_id, ["init", "--initial-branch=main", "--template="])
        self._validate_repository(agent_id)
        if name == "git_status":
            return self._git(agent_id, ["status", "--short", "--untracked-files=all", "--ignore-submodules=all"])
        if name == "git_diff":
            unstaged = self._git(agent_id, ["diff", "--no-ext-diff", "--no-textconv", "--ignore-submodules=all", "--"])
            staged = self._git(agent_id, ["diff", "--cached", "--no-ext-diff", "--no-textconv", "--ignore-submodules=all", "--"])
            return {"ok": unstaged["ok"] and staged["ok"], "unstaged": unstaged, "staged": staged}
        if name == "git_commit":
            message = arguments["message"]
            if not message.strip() or len(message) > 2000 or "\x00" in message:
                raise ToolError("Commit message must contain 1–2000 characters.")
            self._list(agent_id, ".")
            staged = self._git(agent_id, ["add", "--all", "--", ".", ":(exclude).tmp", ":(exclude).env", ":(exclude).env.*"])
            if not staged["ok"]:
                return staged
            return self._git(agent_id, ["commit", "--no-verify", "--no-gpg-sign", "-m", message, "--"])
        if name == "git_push":
            url, branch = arguments["remote_url"], arguments["branch"]
            match = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", url)
            if not match or any(part in {".", ".."} for part in match.groups()):
                raise ToolError("Push destination must be an explicit credential-free https://github.com/OWNER/REPO URL.")
            if not branch or len(branch) > 200 or branch.startswith("-") or any(c.isspace() for c in branch):
                raise ToolError("Invalid destination branch.")
            valid = self._git(agent_id, ["check-ref-format", "--branch", branch])
            if not valid["ok"]:
                raise ToolError("Invalid destination branch.")
            token = os.environ.get("EVO_GITHUB_TOKEN", "")
            if not token:
                raise ToolError("Set EVO_GITHUB_TOKEN in the host environment to authorize GitHub pushes. Credentials are never passed to agent code.")
            return self._git(agent_id, ["push", "--no-verify", "--porcelain", url, f"HEAD:refs/heads/{branch}"], token=token, timeout=60)
        raise ToolError("Unknown Git tool.")
