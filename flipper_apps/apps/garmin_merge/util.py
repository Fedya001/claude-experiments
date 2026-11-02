"""Small helpers shared by the app's modules."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


class Ask(Protocol):
    def __call__(self, prompt: str, *, secret: bool = False) -> str: ...


def mask(secret: str) -> str:
    """'abcdefghijkl' -> 'abcd…ijkl'; never reveals short secrets."""
    return f"{secret[:4]}…{secret[-4:]}" if len(secret) >= 16 else "…"


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, ValueError):
        return None


def write_json(path: Path, data: Any) -> None:
    """Writes a file readable only by the bot's user."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
