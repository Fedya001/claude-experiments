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


def test_rejects_invalid_command():
    bad = App()
    bad.command = "garmin-to-strava"
    with pytest.raises(ValueError):
        Registry().register(bad)


class FakeAPI:
    def __init__(self):
        self.sent = []

    def send_message(self, chat_id, text, **kw):
        self.sent.append(text)
        return {"message_id": len(self.sent)}

    def download_file(self, file_id, dest):
        dest.write_bytes(file_id.encode())
        return dest


class Recorder(App):
    command = "rec"

    def __init__(self):
        self.calls = []

    def handle(self, ctx):
        self.calls.append((ctx.text, [p.read_text() for p in ctx.photos], ctx.data_dir))


def make_runner(tmp_path):
    reg = Registry()
    rec = Recorder()
    reg.register(rec)
    runner = Runner(FakeAPI(), reg, {1}, tmp_path)
    return runner, rec


def msg(**kw):
    return {"chat": {"id": 5}, "from": {"id": kw.pop("user", 1)}, **kw}


def wait_for(cond):
    for _ in range(100):
        if cond():
            return
        time.sleep(0.02)
    raise AssertionError("timed out")


def test_album_is_one_call_with_all_photos(tmp_path):
    runner, rec = make_runner(tmp_path)
    photo = lambda fid: [{"file_id": fid + "_s", "width": 90, "height": 90},
                         {"file_id": fid, "width": 900, "height": 900}]
    runner.on_message(msg(media_group_id="g", photo=photo("a"), caption="/rec today | Ride"))
    runner.on_message(msg(media_group_id="g", photo=photo("b")))
    runner.flush_albums()
    assert rec.calls == []          # still waiting for more photos
    runner.flush_albums(force=True)
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
