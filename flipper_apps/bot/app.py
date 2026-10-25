"""Base class for apps and the context each app invocation receives."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .api import BotAPI

log = logging.getLogger(__name__)

COMMAND_RE = re.compile(r"^[a-z0-9_]{1,32}$")


class AskCancelled(Exception):
    """The user sent /cancel or another command, or didn't answer in time."""


# (chat_id, user_id, timeout) -> (text, message_id), or None if cancelled
WaitForReply = Callable[[int, int, float], "tuple[str, int] | None"]


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
    wait_for_reply: WaitForReply | None = None

    @property
    def user_dir(self) -> Path:
        """Persistent directory for this Telegram user only: data/<command>/users/<id>/."""
        path = self.data_dir / "users" / str(self.user_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ask(self, prompt: str, *, secret: bool = False, timeout: float = 300) -> str:
        """Ask the user a question and wait for their next message in this chat.

        With secret=True the reply is deleted from the chat right after reading it.
        Raises AskCancelled on /cancel, another command, or timeout.
        """
        if self.wait_for_reply is None:
            raise RuntimeError("this context can't ask questions")
        self.reply(prompt + ("\n(Your reply will be deleted from the chat.)" if secret else "")
                   + "\nSend /cancel to stop.")
        answer = self.wait_for_reply(self.chat_id, self.user_id, timeout)
        if answer is None:
            raise AskCancelled()
        text, message_id = answer
        if secret:
            try:
                self.api.delete_message(self.chat_id, message_id)
            except Exception:
                log.warning("could not delete a secret reply", exc_info=True)
                self.reply("⚠️ I couldn't delete your reply. Please delete it yourself.")
        return text.strip()

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
