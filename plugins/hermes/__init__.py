"""Hermes plugin: compress large terminal output with `squeez filter`; see README.md."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_MIN_SAVING = 0.20
_TIMEOUT_S = 10
_KEEP_RAW_S = 24 * 3600


def register(ctx):
    if not _squeez_bin():
        _warn("squeez binary not found; output is left as is until it is installed")
    ctx.register_hook("transform_terminal_output", _transform_terminal_output)


def _hermes_home() -> Path:
    try:
        from hermes_constants import get_hermes_home
        return Path(get_hermes_home())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")


def _squeez_bin() -> str | None:
    for cand in (os.environ.get("SQUEEZ_BIN"), shutil.which("squeez"),
                 str(_hermes_home() / "squeez" / "bin" / "squeez"),
                 str(Path.home() / ".claude" / "squeez" / "bin" / "squeez")):
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None


def _min_chars() -> int:
    try:
        return int(os.environ.get("SQUEEZ_OUTPUT_MIN_CHARS", "4000"))
    except ValueError:
        return 4000


def _raw_dir() -> Path:
    d = _hermes_home() / "cache" / "squeez-raw"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _prune(d: Path) -> None:
    cutoff = time.time() - _KEEP_RAW_S
    for p in d.glob("*.txt"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:
            pass


def _save_raw(command: str, output: str) -> Path:
    # The hook runs before Hermes redacts, so only a redacted copy may reach disk.
    try:
        from agent.redact import redact_terminal_output
        from tools.ansi_strip import strip_ansi
        text = redact_terminal_output(strip_ansi(output), command)
    except Exception:
        raise RuntimeError("redactor unavailable")
    d = _raw_dir()
    _prune(d)
    key = hashlib.sha256((command + "\0" + output).encode("utf-8", "replace")).hexdigest()[:16]
    path = d / f"{key}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as f:
        f.write(text)
    return path


def compress(command: object, output: object) -> str | None:
    if os.environ.get("SQUEEZ_OUTPUT_DISABLE") == "1":
        return None
    if not isinstance(output, str) or len(output) < _min_chars():
        return None
    if not isinstance(command, str) or command.lstrip().startswith("squeez"):
        return None
    exe = _squeez_bin()
    if not exe:
        return None
    env = dict(os.environ)
    env.setdefault("SQUEEZ_DIR", str(_hermes_home() / "squeez"))
    proc = subprocess.run([exe, "filter", command], input=output, capture_output=True,
                          text=True, errors="replace", timeout=_TIMEOUT_S, env=env)
    small = proc.stdout.rstrip("\n")
    if proc.returncode != 0 or not small.strip():
        return None
    if len(small) > len(output) * (1 - _MIN_SAVING):
        return None
    path = _save_raw(command, output)
    return (f"{small}\n[squeez: output compressed {len(output)}→{len(small)} chars. "
            f"Full output: {path} (read_file it if something you need is missing)]")


def _transform_terminal_output(command=None, output=None, **_kw):
    try:
        return compress(command, output)
    except Exception as exc:  # fail open: the model gets the raw output
        _warn(str(exc))
        return None


def _warn(message):
    print(f"squeez: hermes plugin warning: {message}", file=sys.stderr)
