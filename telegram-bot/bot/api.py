"""Thin client for the official Telegram Bot API (https://core.telegram.org/bots/api)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx


class TelegramError(RuntimeError):
    pass


MAX_TEXT = 4096  # Telegram's limit for message text


def _fit(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


class BotAPI:
    def __init__(self, token: str, base_url: str = "https://api.telegram.org"):
        self._url = f"{base_url}/bot{token}"
        self._file_url = f"{base_url}/file/bot{token}"
        # Long polling holds requests open for up to `timeout` seconds.
        self._http = httpx.Client(timeout=httpx.Timeout(70.0, connect=10.0))

    def call(self, method: str, files: dict | None = None, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        if files:
            # multipart: non-string values must be JSON-encoded
            data = {k: v if isinstance(v, str) else json.dumps(v) for k, v in params.items()}
            resp = self._http.post(f"{self._url}/{method}", data=data, files=files)
        else:
            resp = self._http.post(f"{self._url}/{method}", json=params)
        payload = resp.json()
        if not payload.get("ok"):
            raise TelegramError(f"{method}: {payload.get('description', resp.text)}")
        return payload["result"]

    def get_updates(self, offset: int | None = None, timeout: int = 50) -> list[dict]:
        return self.call("getUpdates", offset=offset, timeout=timeout,
                         allowed_updates=["message"])

    def send_message(self, chat_id: int, text: str, **kw: Any) -> dict:
        return self.call("sendMessage", chat_id=chat_id, text=_fit(text),
                         link_preview_options={"is_disabled": True}, **kw)

    def edit_message_text(self, chat_id: int, message_id: int, text: str) -> dict:
        return self.call("editMessageText", chat_id=chat_id, message_id=message_id,
                         text=_fit(text), link_preview_options={"is_disabled": True})

    def send_document(self, chat_id: int, path: Path, caption: str | None = None) -> dict:
        with open(path, "rb") as f:
            return self.call("sendDocument", files={"document": (path.name, f)},
                             chat_id=str(chat_id), caption=caption)

    def download_file(self, file_id: str, dest: Path) -> Path:
        info = self.call("getFile", file_id=file_id)
        resp = self._http.get(f"{self._file_url}/{info['file_path']}")
        resp.raise_for_status()
        dest.write_bytes(resp.content)
        return dest

    def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        self.call("setMyCommands",
                  commands=[{"command": c, "description": d[:256]} for c, d in commands])
