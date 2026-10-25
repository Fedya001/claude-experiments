"""Base class for apps and the context each app invocation receives."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .api import BotAPI

COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")


@dataclass
class Context:
    api: BotAPI
    chat_id: int
    user_id: int
    text: str                       # message text after the command
    photos: list[Path] = field(default_factory=list)
    documents: list[Path] = field(default_factory=list)
    data_dir: Path = Path("data")   # private, persistent directory of the app
    work_dir: Path = Path(".")      # temporary directory, removed after the call

    def reply(self, text: str) -> int:
        """Send a message; returns its id so it can be edited later."""
        return self.api.send_message(self.chat_id, text)["message_id"]

    def edit(self, message_id: int, text: str) -> None:
        self.api.edit_message_text(self.chat_id, message_id, text)

    def send_file(self, path: Path, caption: str | None = None) -> None:
        self.api.send_document(self.chat_id, path, caption)


class App:
    """Subclass, set `command`/`description`, implement `handle`, and export `APP = MyApp()`."""

    command: str = ""
    description: str = ""
    usage: str = ""                 # longer help shown by /help <command>

    def handle(self, ctx: Context) -> None:
        raise NotImplementedError
