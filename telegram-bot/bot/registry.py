"""Discovers apps in the `apps` package: every subpackage exporting `APP`."""
from __future__ import annotations

import importlib
import logging
import pkgutil
from types import ModuleType

from .app import COMMAND_RE, App

log = logging.getLogger(__name__)


class Registry:
    def __init__(self) -> None:
        self.apps: dict[str, App] = {}

    def register(self, app: App) -> None:
        if not COMMAND_RE.match(app.command):
            raise ValueError(f"invalid command {app.command!r}: Telegram allows only a-z, 0-9, _")
        if app.command in self.apps or app.command in ("help", "start"):
            raise ValueError(f"duplicate command /{app.command}")
        self.apps[app.command] = app

    def discover(self, package: ModuleType) -> None:
        for info in pkgutil.iter_modules(package.__path__):
            name = f"{package.__name__}.{info.name}"
            try:
                module = importlib.import_module(name)
            except Exception:
                log.exception("failed to load app %s", name)
                continue
            app = getattr(module, "APP", None)
            if isinstance(app, App):
                self.register(app)
                log.info("loaded /%s from %s", app.command, name)

    def get(self, command: str) -> App | None:
        return self.apps.get(command)

    def commands(self) -> list[tuple[str, str]]:
        return [("help", "List commands")] + [
            (a.command, a.description) for a in sorted(self.apps.values(), key=lambda a: a.command)]

    def help_text(self, command: str | None = None) -> str:
        if command and (app := self.get(command.lstrip("/"))):
            return f"/{app.command} — {app.description}\n\n{app.usage}".strip()
        return "\n".join(f"/{c} — {d}" for c, d in self.commands()) + \
            "\n\n/help <command> for details."
