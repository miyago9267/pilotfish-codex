"""Optional Jev classifier; its output is advisory, never a Pilotfish route marker."""

from __future__ import annotations

import json
import math
import os
import re
import tomllib
from pathlib import Path
from urllib import error, parse, request

ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.13.0"
MAX_PROMPT_CHARS = 4096
MAX_RESPONSE_BYTES = 65536
MAX_TIMEOUT_SECONDS = 1.0
THRESHOLD = 0.8
MIN_LEAD = 0.2

QUESTIONS = {
    "parent_local": {"type": "noul", "instructions": "Is this one clear, bounded action that the parent can do locally without delegation?"},
    "mechanical": {"type": "noul", "instructions": "Is this routine, well-specified, low-judgment work suited to the cheap mech-executor role?"},
    "exploration": {"type": "noul", "instructions": "Is this primarily read-only repository or context reconnaissance suited to scout?"},
    "judgment": {"type": "noul", "instructions": "Does this require normal design, tool choice, interpretation, QA, or bounded multi-step implementation suited to Sol?"},
    "deep_judgment": {"type": "noul", "instructions": "Does this require deep architecture, cross-system tradeoffs, conflicting evidence, or advanced tool orchestration suited to Astra?"},
}
ROUTES = {
    "parent_local": ("guarded", "parent-local"),
    "mechanical": ("mechanical", "mech-executor"),
    "exploration": ("exploration", "scout"),
    "judgment": ("judgment", "sol-executor"),
    "deep_judgment": ("deep_judgment", "executor"),
}
CONFIG_FILE = "pilotfish-jev/config.json"
CACHE_DIR = "plugins/cache/pilotfish-codex/pilotfish-jev-router"
PLUGIN_ID = "pilotfish-jev-router@pilotfish-codex"

_PEM = re.compile(
    r"-----BEGIN [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)-----.*?"
    r"-----END [A-Z ]*(?:PRIVATE KEY|CERTIFICATE)-----",
    re.DOTALL,
)
_SECRET_ASSIGNMENT = re.compile(
    r'''(?ix)\b((?:api[_-]?key|token|password|passwd|secret|authorization|'''
    r'''client[_-]?secret)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)'''
)
_BEARER = re.compile(r"(?i)\bBearer\s+\S+")
_TOKEN = re.compile(r"\b(?:sk-[A-Za-z0-9_-]+|gh[opusr]_[A-Za-z0-9_]+|glpat-[A-Za-z0-9_-]+)\b")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_LONG_OPAQUE = re.compile(r"\b[A-Za-z0-9_/-]{40,}\b")
_URL_QUERY = re.compile(r"(https?://[^\s?#]+)\?[^\s#]+")
_CODE = re.compile(r"```.*?```|`[^`]*`", re.DOTALL)
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_ABSOLUTE_PATH = re.compile(r"(?<!\w)(?:/(?:Users|home|private|tmp|var|etc)/|[A-Za-z]:\\)[^\s,;]+")
_QUOTED = re.compile(r"\"[^\"]{1,500}\"|'[^']{1,500}'")


def _plugin_root(codex_home: Path) -> Path | None:
    """Select a single enabled, identity-matched installed cache release."""
    codex_config = codex_home / "config.toml"
    if codex_config.is_symlink():
        return None
    try:
        if not codex_config.is_file() or codex_config.stat().st_size > 1048576:
            return None
        settings = tomllib.loads(codex_config.read_text(encoding="utf-8"))
        if settings.get("plugins", {}).get(PLUGIN_ID, {}).get("enabled") is not True:
            return None
    except (OSError, UnicodeError, ValueError, TypeError, AttributeError):
        return None

    cache = codex_home
    for part in Path(CACHE_DIR).parts:
        cache /= part
        if cache.is_symlink():
            return None
    if not cache.is_dir():
        return None
    try:
        releases = [entry for entry in cache.iterdir() if entry.is_dir() and not entry.is_symlink()]
    except OSError:
        return None
    valid = []
    for entry in releases:
        module = entry / "jev_router.py"
        manifest = entry / ".codex-plugin/plugin.json"
        if (not module.is_file() or module.is_symlink() or not manifest.is_file()
                or manifest.is_symlink() or manifest.parent.is_symlink()):
            continue
        try:
            if manifest.stat().st_size > 4096:
                continue
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            continue
        if (isinstance(metadata, dict) and metadata.get("name") == "pilotfish-jev-router"
                and metadata.get("version") == entry.name):
            valid.append(entry)
    return valid[0] if len(valid) == 1 else None


def load_config(codex_home: Path) -> tuple[str, Path | None]:
    """Load $CODEX_HOME/pilotfish-jev/config.json with environment overrides.

    The only config shape is {"mode": "shadow"} or {"mode": "active"}.
    Invalid or missing configuration fails closed to ("off", None).
    """
    home = Path(codex_home).expanduser()
    config_dir = home / "pilotfish-jev"
    config_path = home / CONFIG_FILE
    mode = "off"
    if not config_dir.is_symlink() and not config_path.is_symlink():
        try:
            if config_path.is_file() and config_path.stat().st_size <= 4096:
                config = json.loads(config_path.read_text(encoding="utf-8"))
                if isinstance(config, dict) and set(config) == {"mode"}:
                    if config["mode"] in {"shadow", "active"}:
                        mode = config["mode"]
        except (OSError, UnicodeError, ValueError, TypeError):
            pass

    env_mode = os.environ.get("PILOTFISH_JEV_MODE")
    if env_mode is not None:
        mode = env_mode.strip().lower()
    if mode not in {"shadow", "active"}:
        return "off", None

    env_root = os.environ.get("PILOTFISH_JEV_PLUGIN_ROOT")
    if env_root is not None:
        root = Path(env_root.strip()).expanduser() if env_root.strip() else None
        if root is None or not root.is_absolute() or root.is_symlink():
            return "off", None
        module = root / "jev_router.py"
        if not module.is_file() or module.is_symlink():
            return "off", None
        return mode, root

    root = _plugin_root(home)
    return (mode, root) if root is not None else ("off", None)


def redact_prompt(prompt: str) -> str:
    """Remove common credential and personal identifiers before remote inference."""
    text = _CODE.sub("[CODE]", prompt)
    text = _PEM.sub("[REDACTED]", text)
    text = _QUOTED.sub("[QUOTED]", text)
    text = _BEARER.sub("Bearer [REDACTED]", text)
    text = _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", text)
    text = _TOKEN.sub("[REDACTED]", text)
    text = _EMAIL.sub("[REDACTED]", text)
    text = _URL_QUERY.sub(r"\1?[REDACTED]", text)
    text = _URL.sub("[URL]", text)
    text = _ABSOLUTE_PATH.sub("[PATH]", text)
    return _LONG_OPAQUE.sub("[REDACTED]", text)


def _api_key() -> str | None:
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if key:
        return key
    try:
        return (Path.home() / ".config/typesafe/api_key").read_text(
            encoding="utf-8"
        ).strip() or None
    except OSError:
        return None


def _score(response: object, question: str) -> float | None:
    if not isinstance(response, dict):
        return None
    answers = response.get("answers")
    if not isinstance(answers, dict):
        return None
    answer = answers.get(question)
    if not isinstance(answer, dict) or answer.get("type") != "noul":
        return None
    value = answer.get("noul")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= 1:
        return None
    return float(value)


class JevRouter:
    """Return a bounded classification record, or None to keep existing routing."""

    def __init__(
        self,
        mode: str = "off",
        timeout: float = 1.0,
        *,
        _endpoint: str = ENDPOINT,
    ) -> None:
        if mode not in {"off", "shadow", "active"}:
            raise ValueError("invalid Jev router mode")
        if not math.isfinite(timeout) or not 0 < timeout <= MAX_TIMEOUT_SECONDS:
            raise ValueError("invalid Jev router timeout")
        if _endpoint != ENDPOINT:
            parsed = parse.urlsplit(_endpoint)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
                raise ValueError("Jev endpoint must be System One or local test server")
        self.mode = mode
        self.timeout = timeout
        self._endpoint = _endpoint

    def classify(self, prompt: object) -> dict[str, object] | None:
        if (
            self.mode == "off"
            or not isinstance(prompt, str)
            or not prompt.strip()
            or len(prompt) > MAX_PROMPT_CHARS
        ):
            return None
        key = _api_key()
        if not key:
            return None
        body = json.dumps(
            {
                "model": MODEL,
                "state": redact_prompt(prompt),
                "questions": QUESTIONS,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        call = request.Request(
            self._endpoint,
            data=body,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(call, timeout=self.timeout) as reply:
                raw = reply.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                return None
            response = json.loads(raw)
        except error.HTTPError as failure:
            failure.close()
            return None
        except (error.URLError, TimeoutError, OSError, ValueError):
            return None
        if not isinstance(response, dict) or response.get("model") != MODEL:
            return None
        scores = {name: _score(response, name) for name in QUESTIONS}
        if any(score is None for score in scores.values()):
            return None
        record: dict[str, object] = {"mode": self.mode, "model": MODEL, "scores": scores}
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        label, score = ranked[0]
        lead = score - ranked[1][1]
        record.update({"route": ROUTES[label][0], "score": score, "lead": lead})
        if self.mode == "active":
            role = ROUTES[label][1]
            if role is not None and score >= THRESHOLD and lead >= MIN_LEAD:
                record["recommendation"] = {"role": role, "route": ROUTES[label][0]}
            else:
                record.pop("route", None)
                record.pop("score", None)
                record.pop("lead", None)
        return record
