"""Minimal example app — copy this folder to start a new one."""
from bot.app import App, Context


class Ping(App):
    command = "ping"
    description = "Check that the bot is alive"
    usage = "/ping [text] — replies with pong, the text and the number of attached photos."

    def handle(self, ctx: Context) -> None:
        extra = f" {ctx.text}" if ctx.text else ""
        ctx.reply(f"pong{extra} ({len(ctx.photos)} photo(s))")


APP = Ping()
