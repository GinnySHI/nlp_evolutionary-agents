"""Configuration loading; secrets never enter serializable session state."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, sep, value = line.partition("=")
        if not sep or not key.strip().replace("_", "").isalnum():
            raise ValueError(f"Invalid environment entry at line {number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    base_url: str = "https://api1.hkgai.net"
    model: str = "t2_hkgai-v3_fp8_1m_e7"
    data_dir: Path = Path(".evoagents")
    sandbox_backend: str = "auto"
    request_timeout: float = 90
    max_steps: int = 40
    max_output_tokens: int = 4096

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        path = (env_file or Path.cwd() / ".env").resolve()
        values = {**read_env(path), **os.environ}
        base_url = values.get("HKGAI_BASE_URL", cls.base_url).strip().rstrip("/")
        parsed = urlsplit(base_url)
        host = (parsed.hostname or "").lower()
        try:
            port = parsed.port
        except ValueError:
            raise ValueError("HKGAI_BASE_URL contains an invalid port") from None
        if port is not None and port != 443:
            raise ValueError("HKGAI_BASE_URL must use the default HTTPS port 443")
        if parsed.scheme != "https" or not host or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("HKGAI_BASE_URL must be a valid HTTPS API URL without credentials, query or fragment")
        allowed = host == "hkgai.net" or host.endswith(".hkgai.net") or host == "api.deepseek.com"
        if not allowed:
            raise ValueError("Course requirements allow only HKGAI or DeepSeek API domains")
        data_dir = Path(values.get("EVO_DATA_DIR", ".evoagents")).expanduser()
        if not data_dir.is_absolute():
            data_dir = path.parent / data_dir
        backend = values.get("EVO_SANDBOX", "auto")
        if backend not in {"auto", "docker", "macos"}:
            raise ValueError("EVO_SANDBOX must be auto, docker or macos")
        result = cls(
            api_key=values.get("HKGAI_API_KEY", "").strip(), base_url=base_url,
            model=values.get("HKGAI_MODEL", cls.model).strip(), data_dir=data_dir.resolve(),
            sandbox_backend=backend, request_timeout=float(values.get("EVO_REQUEST_TIMEOUT", "90")),
            max_steps=int(values.get("EVO_MAX_STEPS", "40")),
            max_output_tokens=int(values.get("EVO_MAX_OUTPUT_TOKENS", "4096")),
        )
        if not 1 <= result.max_steps <= 1000 or not 1 <= result.max_output_tokens <= 32768 or not 1 <= result.request_timeout <= 600:
            raise ValueError("Step budget, output tokens or request timeout is outside the supported range")
        return result
