"""CCTV resolver backed by the current official Yangshipin client flow."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESOLVER = ROOT / "providers" / "ysp" / "resolve.mjs"


def resolve(channel_id: str, timeout: int = 20) -> str | None:
    """Return a fresh official HLS manifest URL for a public CCTV channel."""
    env = os.environ.copy()
    try:
        result = subprocess.run(
            ["node", str(RESOLVER), channel_id],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Node.js is required for the official CCTV resolver") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("official CCTV resolver timed out") from exc

    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip()
        raise RuntimeError(message or f"official resolver exited {result.returncode}")

    url = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""
    return url if url.startswith(("http://", "https://")) else None
