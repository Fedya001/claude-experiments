"""The app with Garmin stubbed out."""
from pathlib import Path

import pytest

import apps.garmin_merge as app_mod
from apps.garmin_merge.garmin import Activity
from bot.app import Context

FIX = Path(__file__).parent / "fixtures"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjE5MDAwMDAwMDB9.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


class FakeCtx(Context):
    def __init__(self, tmp_path, text, answers=(), user_id=1):
        super().__init__(api=None, chat_id=0, user_id=user_id, text=text,
                         data_dir=tmp_path / "data", work_dir=tmp_path)
        self.messages, self.asked, self.files = [], [], []
        self.answers = list(answers)

    def reply(self, text):
        self.messages.append(text)
        return 0

    def edit(self, message_id, text):
        self.messages.append(text)

    def ask(self, prompt, *, secret=False, timeout=300):
        self.asked.append((prompt, secret))
        return self.answers.pop(0)

    def send_file(self, path, caption=None):
        self.files.append((path.name, path.read_text(), caption))


def connect_garmin(user_dir):
    tokens = user_dir / "garmin_tokens"
    tokens.mkdir(parents=True, exist_ok=True)
    (tokens / "garmin_tokens.json").write_text(
        f'{{"di_token": "{JWT}", "di_refresh_token": "refresh-token-0123456789"}}')
    (user_dir / "garmin_account.json").write_text('{"email": "me@x.org", "name": "Me"}')


@pytest.fixture
def stubs(monkeypatch):
    acts = [Activity(i, n, "road_biking", "", 1.4, (FIX / f"{f}.gpx").read_text())
            for i, n, f in [(1, "Morning Ride", "morning"), (2, "Afternoon Ride", "afternoon")]]
    calls = {"garmin_connect": 0, "found": acts}

    def garmin_login(user_dir, ask):
        if not (user_dir / "garmin_tokens" / "garmin_tokens.json").exists():
            calls["garmin_connect"] += 1
            connect_garmin(user_dir)
        return object()

    def garmin_connect(user_dir, ask, reason=""):
        calls["garmin_connect"] += 1
        connect_garmin(user_dir)

    monkeypatch.setattr(app_mod.garmin, "login", garmin_login)
    monkeypatch.setattr(app_mod.garmin, "connect", garmin_connect)
    monkeypatch.setattr(app_mod.garmin, "find_activities",
                        lambda c, s: [{}] * len(calls["found"]))
    monkeypatch.setattr(app_mod.garmin, "download", lambda c, m: calls["found"])
    return calls


def test_merges_and_sends_gpx_file(tmp_path, stubs):
    ctx = FakeCtx(tmp_path, "today | Lake loop")
    app_mod.APP.handle(ctx)
    [(name, gpx, caption)] = ctx.files
    assert name == "2026-10-25_Lake_loop.gpx" and caption == "Lake loop"
    assert gpx.count("<trkseg>") == 2 and "<name>Lake loop</name>" in gpx
    assert "Merged: " in ctx.messages[-1]
    assert stubs["garmin_connect"] == 1

    app_mod.APP.handle(FakeCtx(tmp_path, "today"))
    assert stubs["garmin_connect"] == 1   # saved login reused


def test_file_name_without_title(tmp_path, stubs):
    ctx = FakeCtx(tmp_path, "yesterday")
    app_mod.APP.handle(ctx)
    assert ctx.files[0][0] == "2026-10-25_merged.gpx" and ctx.files[0][2] is None


def test_nothing_found(tmp_path, stubs):
    stubs["found"] = []
    ctx = FakeCtx(tmp_path, "today")
    app_mod.APP.handle(ctx)
    assert "No Garmin activities" in ctx.messages[-1] and ctx.files == []


def test_account_is_masked_and_per_user(tmp_path):
    connect_garmin(tmp_path / "data" / "users" / "1")
    mine = FakeCtx(tmp_path, "account", user_id=1)
    app_mod.APP.handle(mine)
    text = mine.messages[-1]
    assert "Me (me@x.org)" in text and "eyJh…" in text and JWT not in text
    assert "refresh-token-0123456789" not in text and "expires 2030-03-17" in text

    other = FakeCtx(tmp_path, "account", user_id=2)
    app_mod.APP.handle(other)
    assert "me@x.org" not in other.messages[-1] and "not connected" in other.messages[-1]


def test_forget_asks_and_deletes_only_own_login(tmp_path):
    for uid in ("1", "2"):
        connect_garmin(tmp_path / "data" / "users" / uid)
    app_mod.APP.handle(FakeCtx(tmp_path, "forget", answers=["no"]))
    assert (tmp_path / "data/users/1/garmin_tokens/garmin_tokens.json").exists()

    yes = FakeCtx(tmp_path, "logout", answers=["yes"])
    app_mod.APP.handle(yes)
    assert not (tmp_path / "data/users/1/garmin_tokens/garmin_tokens.json").exists()
    assert (tmp_path / "data/users/2/garmin_tokens/garmin_tokens.json").exists()
    assert "Forgot your Garmin login" in yes.messages[-1]

    nothing = FakeCtx(tmp_path, "forget")
    app_mod.APP.handle(nothing)
    assert "Nothing to forget" in nothing.messages[-1]


def test_login_replaces_only_after_confirmation(tmp_path, stubs):
    connect_garmin(tmp_path / "data" / "users" / "1")
    app_mod.APP.handle(FakeCtx(tmp_path, "login", answers=["no"]))
    assert stubs["garmin_connect"] == 0
    ctx = FakeCtx(tmp_path, "connect garmin", answers=["yes"])
    app_mod.APP.handle(ctx)
    assert stubs["garmin_connect"] == 1 and "Garmin connected" in ctx.messages[-1]


def test_bad_subcommand_argument_shows_usage(tmp_path):
    ctx = FakeCtx(tmp_path, "forget strava")
    app_mod.APP.handle(ctx)
    assert ctx.messages[-1].startswith("Usage:") and "/garmin_merge help" in ctx.messages[-1]


@pytest.mark.parametrize("text", ["", "help", "HELP"])
def test_help_and_bare_command_show_usage_without_merging(tmp_path, stubs, text):
    ctx = FakeCtx(tmp_path, text)
    app_mod.APP.handle(ctx)
    assert ctx.messages == [app_mod.USAGE] and ctx.files == []
    assert stubs["garmin_connect"] == 0


def test_bad_selector_points_to_help(tmp_path, stubs):
    ctx = FakeCtx(tmp_path, "tomorrowish | Title")
    app_mod.APP.handle(ctx)
    assert ctx.messages[-1].startswith("❌ unknown word 'tomorrowish'")
    assert "/garmin_merge help" in ctx.messages[-1] and ctx.files == []
