import time

import pytest

import apps
from bot.app import App
from bot.registry import Registry
from bot.runner import Runner, parse_command


@pytest.mark.parametrize("text,expected", [
    ("/ping", ("ping", "")),
    ("/Ping@MyBot hello there", ("ping", "hello there")),
    ("/garmin_to_strava\ntoday | Ride", ("garmin_to_strava", "today | Ride")),
    ("hello", None),
])
def test_parse_command(text, expected):
    assert parse_command(text) == expected


def test_discovers_bundled_apps():
    reg = Registry()
    reg.discover(apps)
    assert {"ping", "garmin_to_strava"} <= set(reg.apps)
    assert reg.commands()[0][0] == "help"


@pytest.mark.parametrize("command,description", [
    ("garmin-to-strava", "x"), ("Garmin", "x"), ("help", "x"), ("cancel", "x"), ("nodesc", "")])
def test_rejects_invalid_apps(command, description):
    bad = App()
    bad.command, bad.description = command, description
    with pytest.raises(ValueError):
        Registry().register(bad)


def test_discover_skips_invalid_app_and_keeps_others(tmp_path, monkeypatch):
    pkg = tmp_path / "someapps"
    for name, cmd in [("good", "good"), ("bad", "Bad")]:
        (pkg / name).mkdir(parents=True)
        (pkg / name / "__init__.py").write_text(
            "from bot.app import App\n"
            f"class A(App):\n    command = {cmd!r}\n    description = 'd'\n"
            "APP = A()\n")
    (pkg / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path))
    import importlib
    reg = Registry()
    reg.discover(importlib.import_module("someapps"))
    assert set(reg.apps) == {"good"}


class FakeAPI:
    def __init__(self):
        self.sent = []
        self.deleted = []
        self.fail = False

    def send_message(self, chat_id, text, **kw):
        if self.fail:
            raise RuntimeError("network down")
        self.sent.append(text)
        return {"message_id": len(self.sent)}

    def delete_message(self, chat_id, message_id):
        self.deleted.append(message_id)

    def download_file(self, file_id, dest):
        dest.write_bytes(file_id.encode())
        return dest


class Recorder(App):
    command = "rec"
    description = "records calls"

    def __init__(self):
        self.calls = []

    def handle(self, ctx):
        self.calls.append((ctx.text, [p.read_text() for p in ctx.photos], ctx.data_dir))


def make_runner(tmp_path):
    reg = Registry()
    rec = Recorder()
    reg.register(rec)
    runner = Runner(FakeAPI(), reg, {1, 3}, tmp_path)
    return runner, rec


def msg(**kw):
    return {"chat": {"id": 5, "type": kw.pop("chat_type", "private")},
            "from": {"id": kw.pop("user", 1)}, **kw}


def wait_for(cond):
    for _ in range(100):
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_album_is_one_call_with_all_photos(tmp_path, monkeypatch):
    runner, rec = make_runner(tmp_path)
    photo = lambda fid: [{"file_id": fid + "_s", "width": 90, "height": 90},
                         {"file_id": fid, "width": 900, "height": 900}]
    runner.on_message(msg(media_group_id="g", photo=photo("a"), caption="/rec today | Ride"))
    runner.on_message(msg(media_group_id="g", photo=photo("b")))
    runner.flush_albums()
    assert rec.calls == []          # still waiting for more photos
    monkeypatch.setattr("bot.runner.ALBUM_WAIT", 0)
    runner.flush_albums()
    wait_for(lambda: rec.calls)
    text, photos, data_dir = rec.calls[0]
    assert text == "today | Ride" and photos == ["a", "b"]
    assert data_dir == tmp_path / "rec" and data_dir.is_dir()


def test_ignores_strangers_and_reports_unknown(tmp_path):
    runner, rec = make_runner(tmp_path)
    runner.on_message(msg(user=2, text="/rec"))
    assert runner.api.sent == [] and rec.calls == []
    runner.on_message(msg(text="/nope"))
    assert "Unknown command" in runner.api.sent[-1]
    runner.on_message(msg(text="/help"))
    assert "/rec" in runner.api.sent[-1]


def test_errors_while_handling_updates_do_not_stop_polling(tmp_path):
    runner, rec = make_runner(tmp_path)
    runner.api.fail = True
    runner._safely(runner.on_message, msg(text="/nope"))   # must not raise
    runner.api.fail = False
    runner._safely(runner.on_message, msg(text="/rec hi"))
    wait_for(lambda: rec.calls)
    assert rec.calls[0][0] == "hi"


def test_long_error_is_truncated(tmp_path):
    from bot.runner import MAX_ERROR

    class Boom(App):
        command, description = "boom", "fails"

        def handle(self, ctx):
            raise RuntimeError("x" * 10_000)

    runner, _ = make_runner(tmp_path)
    runner._run_app(Boom(), [msg(text="/boom")], "")
    assert len(runner.api.sent[-1]) < MAX_ERROR + 50


def test_api_truncates_text():
    from bot.api import MAX_TEXT, _fit
    assert len(_fit("a" * 5000)) == MAX_TEXT and _fit("short") == "short"


class Asker(App):
    command, description = "askme", "asks a secret question"

    def __init__(self):
        self.answers = []

    def handle(self, ctx):
        from bot.app import AskCancelled
        try:
            self.answers.append(ctx.ask("Password?", secret=True, timeout=5))
        except AskCancelled:
            self.answers.append("cancelled")
            raise


def ask_runner(tmp_path):
    runner, _ = make_runner(tmp_path)
    app = Asker()
    runner.registry.register(app)
    return runner, app


def test_ask_gets_reply_and_deletes_secret(tmp_path):
    runner, app = ask_runner(tmp_path)
    runner.on_message(msg(text="/askme"))
    wait_for(lambda: runner._waiting)
    runner.on_message(msg(user=3, text="not me", message_id=5))   # another user
    runner.on_message(msg(text="hunter2", message_id=77))
    wait_for(lambda: app.answers)
    assert app.answers == ["hunter2"] and runner.api.deleted == [77]
    assert "Password?" in runner.api.sent[0]


def test_cancel_stops_question(tmp_path):
    runner, app = ask_runner(tmp_path)
    runner.on_message(msg(text="/askme"))
    wait_for(lambda: runner._waiting)
    runner.on_message(msg(text="/cancel"))
    wait_for(lambda: any("Cancelled /askme" in t for t in runner.api.sent))
    assert app.answers == ["cancelled"]
    runner.on_message(msg(text="/cancel"))
    assert runner.api.sent[-1] == "Nothing to cancel."


def test_other_command_cancels_question_and_runs(tmp_path):
    runner, app = ask_runner(tmp_path)
    runner.on_message(msg(text="/askme"))
    wait_for(lambda: runner._waiting)
    runner.on_message(msg(text="/help"))
    wait_for(lambda: app.answers)
    assert app.answers == ["cancelled"]
    assert any("/askme" in t and "/help" in t for t in runner.api.sent)


def test_user_dir_is_per_user(tmp_path):
    from bot.app import Context
    a = Context(api=None, chat_id=1, user_id=1, text="", data_dir=tmp_path)
    b = Context(api=None, chat_id=1, user_id=2, text="", data_dir=tmp_path)
    assert a.user_dir != b.user_dir and a.user_dir.is_dir() and a.user_dir.name == "1"


def test_group_chats_are_ignored(tmp_path):
    runner, rec = make_runner(tmp_path)
    for chat_type in ("group", "supergroup", "channel"):
        runner.on_message(msg(chat_type=chat_type, text="/rec hi"))
    runner.on_message(msg(chat_type="group", text="/help"))
    assert runner.api.sent == [] and rec.calls == []


def test_logging_hides_request_urls_with_the_token():
    import logging

    from bot.__main__ import setup_logging
    setup_logging()
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)
    assert not logging.getLogger("httpcore").isEnabledFor(logging.INFO)


def test_file_download_error_does_not_reveal_token(tmp_path):
    import httpx

    from bot.api import BotAPI, TelegramError

    def handler(request):
        if request.url.path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_path": "x.jpg"}})
        return httpx.Response(404)
    api = BotAPI("123:SECRET")
    api._http = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(TelegramError) as err:
        api.download_file("f", tmp_path / "x.jpg")
    assert "SECRET" not in str(err.value)
