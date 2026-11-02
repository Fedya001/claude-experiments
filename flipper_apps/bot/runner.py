"""Long-polling loop: routes /commands to apps, each call in its own thread."""
from __future__ import annotations

import logging
import queue
import shutil
import tempfile
import threading
import time
from pathlib import Path

from .api import BotAPI
from .app import AskCancelled, Context
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
        # Apps waiting for an answer from a user: (chat_id, user_id) -> reply queue
        self._waiting: dict[tuple[int, int], queue.Queue] = {}
        self._waiting_lock = threading.Lock()

    def wait_for_reply(self, chat_id: int, user_id: int, timeout: float):
        q: queue.Queue = queue.Queue(maxsize=1)
        key = (chat_id, user_id)
        with self._waiting_lock:
            if old := self._waiting.get(key):
                old.put(None)  # only the newest question per user is answered
            self._waiting[key] = q
        try:
            return q.get(timeout=timeout)
        except queue.Empty:
            self.api.send_message(chat_id, "⌛ No answer received, cancelled.")
            return None
        finally:
            with self._waiting_lock:
                if self._waiting.get(key) is q:
                    del self._waiting[key]

    def _answer_waiting(self, msg: dict) -> bool:
        """Routes a reply to a waiting question; True if the message was consumed."""
        key = (msg["chat"]["id"], msg["from"]["id"])
        with self._waiting_lock:
            q = self._waiting.pop(key, None)
        if q is None:
            return False
        text = msg.get("text") or ""
        if text.startswith("/"):
            q.put(None)  # any command cancels the question
            return parse_command(text)[0] == "cancel"
        if not text:
            with self._waiting_lock:
                self._waiting[key] = q  # keep waiting
            self.api.send_message(key[0], "Please answer with a text message, or send /cancel.")
            return True
        q.put((text, msg["message_id"]))
        return True

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
        if msg.get("chat", {}).get("type") != "private":
            # In groups others would see questions and answers, and bots can't delete
            # messages there without admin rights, so apps only run in one-to-one chats.
            log.warning("ignoring message in non-private chat %s", msg["chat"].get("id"))
            return
        if self._answer_waiting(msg):
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
        if name == "cancel":
            self.api.send_message(chat_id, "Nothing to cancel.")
            return
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
                          photos=photos, documents=documents, data_dir=data_dir, work_dir=work_dir,
                          wait_for_reply=self.wait_for_reply)
            app.handle(ctx)
        except AskCancelled:
            self._safely(self.api.send_message, chat_id, f"Cancelled /{app.command}.")
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
