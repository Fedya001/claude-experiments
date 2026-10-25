"""The app with Garmin, Strava and the browser stubbed out."""
from pathlib import Path

import pytest

import apps.garmin_to_strava as app_mod
from apps.garmin_to_strava.garmin import Activity
from bot.app import Context

FIX = Path(__file__).parent / "fixtures"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjE5MDAwMDAwMDB9.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


class FakeCtx(Context):
    def __init__(self, tmp_path, text, photos=(), answers=(), user_id=1):
        super().__init__(api=None, chat_id=0, user_id=user_id, text=text, photos=list(photos),
                         data_dir=tmp_path / "data", work_dir=tmp_path)
        self.messages, self.files, self.asked = [], [], []
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
        self.files.append(path.read_text())


def connect_garmin(user_dir):
    tokens = user_dir / "garmin_tokens"
    tokens.mkdir(parents=True, exist_ok=True)
    (tokens / "garmin_tokens.json").write_text(
        f'{{"di_token": "{JWT}", "di_refresh_token": "refresh-token-0123456789"}}')
    (user_dir / "garmin_account.json").write_text('{"email": "me@x.org", "name": "Me"}')


def connect_strava(user_dir, ask=None, reason=""):
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "strava_web_state.json").write_text('{"cookies": [{"domain": ".strava.com"}]}')
    (user_dir / "strava_account.json").write_text('{"email": "me@x.org", "name": "Me"}')


@pytest.fixture
def stubs(monkeypatch):
    acts = [Activity(i, n, "road_biking", "", 1.4, (FIX / f"{f}.gpx").read_text())
            for i, n, f in [(1, "Morning Ride", "morning"), (2, "Afternoon Ride", "afternoon")]]
    calls = {"garmin_connect": 0, "strava_connect": 0, "uploads": [], "expire_once": False}

    def garmin_login(user_dir, ask):
        if not (user_dir / "garmin_tokens" / "garmin_tokens.json").exists():
            calls["garmin_connect"] += 1
            connect_garmin(user_dir)
        return object()

    def strava_connect(user_dir, ask, reason=""):
        calls["strava_connect"] += 1
        connect_strava(user_dir)

    def upload(user_dir, gpx, name, description, sport, photos):
        if calls["expire_once"]:
            calls["expire_once"] = False
            raise app_mod.strava_web.SessionExpired()
        calls["uploads"].append((gpx.read_text(), name, description, sport, photos))
        return 42, False, None

    monkeypatch.setattr(app_mod.garmin, "login", garmin_login)
    monkeypatch.setattr(app_mod.garmin, "find_activities", lambda c, s: [{}, {}])
    monkeypatch.setattr(app_mod.garmin, "download", lambda c, m: acts)
    monkeypatch.setattr(app_mod.strava_web, "connect", strava_connect)
    monkeypatch.setattr(app_mod.strava_web, "upload", upload)
    return calls


def test_dry_run_needs_only_garmin(tmp_path, stubs):
    ctx = FakeCtx(tmp_path, "dry today | Test")
    app_mod.APP.handle(ctx)
    assert len(ctx.files) == 1 and ctx.files[0].count("<trkseg>") == 2
    assert stubs["garmin_connect"] == 1 and stubs["strava_connect"] == 0
    assert stubs["uploads"] == []


def test_first_full_run_connects_both_then_reuses(tmp_path, stubs):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    ctx = FakeCtx(tmp_path, "today | Lake loop | Windy", [photo])
    app_mod.APP.handle(ctx)
    _, name, desc, sport, photos = stubs["uploads"][0]
    assert (name, desc, sport, photos) == ("Lake loop", "Windy", "Ride", [photo])
    assert "strava.com/activities/42" in ctx.messages[-2] and "1 photo(s) added" in ctx.messages[-1]
    app_mod.APP.handle(FakeCtx(tmp_path, "today"))
    assert stubs["garmin_connect"] == 1 and stubs["strava_connect"] == 1


def test_only_missing_login_is_asked(tmp_path, stubs):
    connect_garmin(tmp_path / "data" / "users" / "1")
    app_mod.APP.handle(FakeCtx(tmp_path, "today"))
    assert stubs["garmin_connect"] == 0 and stubs["strava_connect"] == 1


def test_expired_strava_session_logs_in_again_and_retries(tmp_path, stubs):
    user_dir = tmp_path / "data" / "users" / "1"
    connect_garmin(user_dir)
    connect_strava(user_dir)
    stubs["expire_once"] = True
    app_mod.APP.handle(FakeCtx(tmp_path, "today"))
    assert stubs["strava_connect"] == 1 and len(stubs["uploads"]) == 1


def test_accounts_are_masked_and_per_user(tmp_path):
    connect_garmin(tmp_path / "data" / "users" / "1")
    mine = FakeCtx(tmp_path, "accounts", user_id=1)
    app_mod.APP.handle(mine)
    text = mine.messages[-1]
    assert "Me (me@x.org)" in text and "eyJh…" in text and JWT not in text
    assert "refresh-token-0123456789" not in text and "expires 2030-03-17" in text
    assert "Strava:\n  not connected" in text

    other = FakeCtx(tmp_path, "accounts", user_id=2)
    app_mod.APP.handle(other)
    assert "me@x.org" not in other.messages[-1]
    assert other.messages[-1].count("not connected") == 2


def test_forget_asks_and_deletes_only_own_data(tmp_path):
    for uid in ("1", "2"):
        connect_garmin(tmp_path / "data" / "users" / uid)
        connect_strava(tmp_path / "data" / "users" / uid)
    no = FakeCtx(tmp_path, "forget all", answers=["no"])
    app_mod.APP.handle(no)
    assert (tmp_path / "data/users/1/strava_web_state.json").exists()

    yes = FakeCtx(tmp_path, "forget strava", answers=["yes"])
    app_mod.APP.handle(yes)
    assert not (tmp_path / "data/users/1/strava_web_state.json").exists()
    assert (tmp_path / "data/users/1/garmin_tokens/garmin_tokens.json").exists()
    assert (tmp_path / "data/users/2/strava_web_state.json").exists()
    assert "Forgot your Strava login" in yes.messages[-1]

    nothing = FakeCtx(tmp_path, "forget strava")
    app_mod.APP.handle(nothing)
    assert "Nothing to forget" in nothing.messages[-1]


def test_connect_replaces_only_after_confirmation(tmp_path, stubs):
    connect_strava(tmp_path / "data" / "users" / "1")
    app_mod.APP.handle(FakeCtx(tmp_path, "connect strava", answers=["no"]))
    assert stubs["strava_connect"] == 0
    ctx = FakeCtx(tmp_path, "connect strava", answers=["yes"])
    app_mod.APP.handle(ctx)
    assert stubs["strava_connect"] == 1 and "Strava connected" in ctx.messages[-1]


def test_bad_subcommand_argument_shows_usage(tmp_path):
    ctx = FakeCtx(tmp_path, "forget everything")
    app_mod.APP.handle(ctx)
    assert ctx.messages[-1].startswith("Usage:")
