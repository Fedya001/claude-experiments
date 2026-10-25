"""The app with Garmin and Strava stubbed out."""
import json
from pathlib import Path

import httpx
import pytest

import apps.garmin_to_strava as app_mod
from apps.garmin_to_strava import strava_api
from apps.garmin_to_strava.garmin import Activity
from bot.app import Context

FIX = Path(__file__).parent / "fixtures"
JWT = "eyJhbGciOiJIUzI1NiJ9.eyJleHAiOjE5MDAwMDAwMDB9.c2lnbmF0dXJlLXNpZ25hdHVyZQ"


class FakeCtx(Context):
    def __init__(self, tmp_path, text, photos=(), answers=(), user_id=1):
        super().__init__(api=None, chat_id=0, user_id=user_id, text=text, photos=list(photos),
                         data_dir=tmp_path / "data", work_dir=tmp_path)
        self.messages, self.asked = [], []
        self.answers = list(answers)

    def reply(self, text):
        self.messages.append(text)
        return 0

    def edit(self, message_id, text):
        self.messages.append(text)

    def ask(self, prompt, *, secret=False, timeout=300):
        self.asked.append((prompt, secret))
        return self.answers.pop(0)


def connect_garmin(user_dir):
    tokens = user_dir / "garmin_tokens"
    tokens.mkdir(parents=True, exist_ok=True)
    (tokens / "garmin_tokens.json").write_text(
        f'{{"di_token": "{JWT}", "di_refresh_token": "refresh-token-0123456789"}}')
    (user_dir / "garmin_account.json").write_text('{"email": "me@x.org", "name": "Me"}')


def connect_strava(user_dir, ask=None, reason=""):
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "strava_tokens.json").write_text(json.dumps({
        "access_token": "s" * 40, "refresh_token": "t" * 40, "expires_at": 1900000000,
        "athlete": "Strava Me", "scope": "read,activity:write,activity:read_all"}))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """strava_api.forget revokes access over HTTP; answer it locally."""
    revoked = []

    def handler(request):
        revoked.append(str(request.url))
        return httpx.Response(200, json={})
    monkeypatch.setattr(strava_api, "new_http",
                        lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    return revoked


class FakeStrava:
    uploads, updates = [], []
    revoked_once = False
    duplicate = False

    def __init__(self, user_dir, http=None):
        pass

    def upload_gpx(self, path, name, description, external_id):
        if FakeStrava.revoked_once:
            FakeStrava.revoked_once = False
            raise strava_api.NotConnected()
        self.uploads.append((path.read_text(), name, description, external_id))
        return (99, True) if FakeStrava.duplicate else (42, False)

    def update_activity(self, activity_id, **fields):
        self.updates.append((activity_id, fields))

    def activities_between(self, start, end):
        return [{"id": 42, "start_date": "2026-10-25T08:00:00Z", "elapsed_time": 600},
                {"id": 7, "start_date": "2026-10-25T08:00:00Z", "elapsed_time": 600},
                {"id": 8, "start_date": "2026-10-24T08:00:00Z", "elapsed_time": 600}]

    def deauthorize(self):
        pass


@pytest.fixture
def stubs(monkeypatch):
    acts = [Activity(i, n, "road_biking", "", 1.4, (FIX / f"{f}.gpx").read_text())
            for i, n, f in [(1, "Morning Ride", "morning"), (2, "Afternoon Ride", "afternoon")]]
    calls = {"garmin_connect": 0, "strava_connect": 0}

    def garmin_login(user_dir, ask):
        if not (user_dir / "garmin_tokens" / "garmin_tokens.json").exists():
            calls["garmin_connect"] += 1
            connect_garmin(user_dir)
        return object()

    def strava_connect(user_dir, ask, reason=""):
        calls["strava_connect"] += 1
        connect_strava(user_dir)

    monkeypatch.setattr(app_mod.garmin, "login", garmin_login)
    monkeypatch.setattr(app_mod.garmin, "find_activities", lambda c, s: [{}, {}])
    monkeypatch.setattr(app_mod.garmin, "download", lambda c, m: acts)
    monkeypatch.setattr(strava_api, "connect", strava_connect)
    monkeypatch.setattr(strava_api, "Strava", FakeStrava)
    FakeStrava.uploads, FakeStrava.updates = [], []
    FakeStrava.revoked_once = FakeStrava.duplicate = False
    return calls


def test_first_run_connects_both_uploads_and_reminds_about_photos(tmp_path, stubs):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    ctx = FakeCtx(tmp_path, "today | Lake loop | Windy", [photo])
    app_mod.APP.handle(ctx)
    gpx, name, desc, ext = FakeStrava.uploads[0]
    assert gpx.count("<trkseg>") == 2 and (name, desc) == ("Lake loop", "Windy")
    assert ext.startswith("garmin-")
    assert FakeStrava.updates == [(42, {"sport_type": "Ride"})]
    final = ctx.messages[-1]
    assert "strava.com/activities/42" in final
    assert "activities/7" in final and "activities/8" not in final   # only overlapping ones
    assert "Add your 1 photo(s) in the Strava app" in final
    assert stubs == {"garmin_connect": 1, "strava_connect": 1}

    app_mod.APP.handle(FakeCtx(tmp_path, "today"))
    assert stubs == {"garmin_connect": 1, "strava_connect": 1}   # reused


def test_only_missing_login_is_asked(tmp_path, stubs):
    connect_garmin(tmp_path / "data" / "users" / "1")
    app_mod.APP.handle(FakeCtx(tmp_path, "today"))
    assert stubs == {"garmin_connect": 0, "strava_connect": 1}


def test_revoked_strava_access_reconnects_and_retries(tmp_path, stubs):
    user_dir = tmp_path / "data" / "users" / "1"
    connect_garmin(user_dir)
    connect_strava(user_dir)
    FakeStrava.revoked_once = True
    app_mod.APP.handle(FakeCtx(tmp_path, "today"))
    assert stubs["strava_connect"] == 1 and len(FakeStrava.uploads) == 1


def test_duplicate_upload_updates_existing_activity(tmp_path, stubs):
    FakeStrava.duplicate = True
    ctx = FakeCtx(tmp_path, "today | New title | New desc")
    app_mod.APP.handle(ctx)
    assert FakeStrava.updates == [
        (99, {"sport_type": "Ride", "name": "New title", "description": "New desc"})]
    assert any("updated it" in m for m in ctx.messages)


def test_accounts_are_masked_and_per_user(tmp_path):
    connect_garmin(tmp_path / "data" / "users" / "1")
    connect_strava(tmp_path / "data" / "users" / "1")
    mine = FakeCtx(tmp_path, "accounts", user_id=1)
    app_mod.APP.handle(mine)
    text = mine.messages[-1]
    assert "Me (me@x.org)" in text and "eyJh…" in text and JWT not in text
    assert "refresh-token-0123456789" not in text and "expires 2030-03-17" in text
    assert "Athlete: Strava Me" in text and "ssss…ssss" in text and "s" * 40 not in text

    other = FakeCtx(tmp_path, "accounts", user_id=2)
    app_mod.APP.handle(other)
    assert "me@x.org" not in other.messages[-1] and "Strava Me" not in other.messages[-1]
    assert other.messages[-1].count("not connected") == 2


def test_forget_asks_revokes_and_deletes_only_own_data(tmp_path, no_network):
    for uid in ("1", "2"):
        connect_garmin(tmp_path / "data" / "users" / uid)
        connect_strava(tmp_path / "data" / "users" / uid)
    app_mod.APP.handle(FakeCtx(tmp_path, "forget all", answers=["no"]))
    assert (tmp_path / "data/users/1/strava_tokens.json").exists() and not no_network

    yes = FakeCtx(tmp_path, "forget strava", answers=["yes"])
    app_mod.APP.handle(yes)
    assert not (tmp_path / "data/users/1/strava_tokens.json").exists()
    assert no_network == ["https://www.strava.com/oauth/deauthorize"]
    assert (tmp_path / "data/users/1/garmin_tokens/garmin_tokens.json").exists()
    assert (tmp_path / "data/users/2/strava_tokens.json").exists()
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
