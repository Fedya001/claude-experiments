"""Long-polling loop: routes /commands to apps, each call in its own thread."""
from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from pathlib import Path

from .api import BotAPI
from .app import Context
from .registry import Registry

log = logging.getLogger(__name__)

ALBUM_WAIT = 1.5  # seconds to wait for the remaining photos of an album
MAX_ERROR = 1000  # error texts can carry whole HTTP response bodies


def parse_command(text: str) -> tuple[str, str] | None:
    """'/cmd@MyBot args' -> ('cmd', 'args'); None if text is not a command."""
    text = text.strip()
    if not text.startswith("/"):
        return None
    head, _, rest = text.partition(" ")
    if "\n" in head:  # '/cmd\nargs'
        head, _, more = head.partition("\n")
        rest = more + (" " + rest if rest else "")
    return head[1:].split("@", 1)[0].lower(), rest.strip()


class Runner:
    def __init__(self, api: BotAPI, registry: Registry, allowed_users: set[int],
                 data_root: Path):
        self.api = api
        self.registry = registry
        self.allowed_users = allowed_users
        self.data_root = data_root
        self._albums: dict[str, tuple[float, list[dict]]] = {}

    def run_forever(self) -> None:
        try:
            self.api.set_my_commands(self.registry.commands())
        except Exception:
            log.exception("setMyCommands failed; the command menu may be stale")
        offset = None
        log.info("polling; commands: %s", ", ".join(self.registry.apps))
        while True:
            try:
                updates = self.api.get_updates(offset, timeout=1 if self._albums else 50)
            except Exception:
                log.exception("getUpdates failed; retrying")
                time.sleep(5)
                continue
            for update in updates:
                offset = update["update_id"] + 1
                if msg := update.get("message"):
                    self._safely(self.on_message, msg)
            self.flush_albums()

    @staticmethod
    def _safely(fn, *args) -> None:
        """Errors while handling one update must not stop the loop: Telegram would
        redeliver the unconfirmed batch after a restart and rerun its commands."""
        try:
            fn(*args)
        except Exception:
            log.exception("handling update failed")

    def on_message(self, msg: dict) -> None:
        if msg.get("from", {}).get("id") not in self.allowed_users:
            log.warning("ignoring message from %s", msg.get("from"))
            return
        if group := msg.get("media_group_id"):
            _, items = self._albums.get(group, (0.0, []))
            self._albums[group] = (time.monotonic(), items + [msg])
        else:
            self.dispatch([msg])

    def flush_albums(self) -> None:
        now = time.monotonic()
        for group, (last, items) in list(self._albums.items()):
            if now - last >= ALBUM_WAIT:
                del self._albums[group]
                self._safely(self.dispatch, items)

    def dispatch(self, messages: list[dict]) -> None:
        chat_id = messages[0]["chat"]["id"]
        text = next((m.get("text") or m.get("caption") for m in messages
                     if m.get("text") or m.get("caption")), "")
        cmd = parse_command(text)
        if cmd is None:
            self.api.send_message(chat_id, "Send a command, e.g. /help. "
                                  "Put the command in the caption when attaching photos.")
            return
        name, args = cmd
        if name in ("help", "start"):
            self.api.send_message(chat_id, self.registry.help_text(args or None))
            return
        app = self.registry.get(name)
        if app is None:
            self.api.send_message(chat_id, f"Unknown command /{name}. Try /help.")
            return
        threading.Thread(target=self._run_app, args=(app, messages, args), daemon=True).start()

    def _run_app(self, app, messages: list[dict], args: str) -> None:
        first = messages[0]
        chat_id = first["chat"]["id"]
        work_dir = Path(tempfile.mkdtemp(prefix=f"{app.command}-"))
        data_dir = self.data_root / app.command
        data_dir.mkdir(parents=True, exist_ok=True)
        try:
            photos, documents = self._download_media(messages, work_dir)
            ctx = Context(api=self.api, chat_id=chat_id, user_id=first["from"]["id"], text=args,
                          photos=photos, documents=documents, data_dir=data_dir, work_dir=work_dir)
            app.handle(ctx)
        except Exception as e:
            log.exception("/%s failed", app.command)
            try:
                self.api.send_message(chat_id,
                                      f"❌ /{app.command} failed: {str(e)[:MAX_ERROR]}")
            except Exception:
                log.exception("could not report failure")
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)

    def _download_media(self, messages: list[dict], work_dir: Path) -> tuple[list[Path], list[Path]]:
        photos, documents = [], []
        for i, m in enumerate(messages):
            if sizes := m.get("photo"):
                biggest = max(sizes, key=lambda s: s.get("file_size", 0) or s["width"] * s["height"])
                photos.append(self.api.download_file(biggest["file_id"], work_dir / f"photo_{i:02d}.jpg"))
            elif doc := m.get("document"):
                # Images sent "as file" keep full quality; treat them as photos.
                name = Path(doc.get("file_name") or f"file_{i:02d}").name
                path = self.api.download_file(doc["file_id"], work_dir / f"{i:02d}_{name}")
                is_image = (doc.get("mime_type") or "").startswith("image/")
                (photos if is_image else documents).append(path)
        return photos, documents
