"""End-to-end run of the app with Garmin, Strava and the browser stubbed out."""
from pathlib import Path

import pytest

import apps.garmin_to_strava as app_mod
from apps.garmin_to_strava.garmin import Activity
from bot.app import Context

FIX = Path(__file__).parent / "fixtures"


class FakeCtx(Context):
    def __init__(self, tmp_path, text, photos=()):
        super().__init__(api=None, chat_id=0, user_id=0, text=text, photos=list(photos),
                         data_dir=tmp_path / "data", work_dir=tmp_path)
        self.messages, self.files = [], []

    def reply(self, text):
        self.messages.append(text)
        return 0

    def edit(self, message_id, text):
        self.messages.append(text)

    def send_file(self, path, caption=None):
        self.files.append(path.read_text())


class FakeStrava:
    uploads, updates = [], []

    def __init__(self, data_dir):
        pass

    def upload_gpx(self, path, name, description, external_id):
        self.uploads.append((path.read_text(), name, description, external_id))
        return 42, False

    def update_activity(self, activity_id, **fields):
        self.updates.append((activity_id, fields))

    def activities_between(self, start, end):
        return [{"id": 42, "start_date": "2026-10-25T08:00:00Z", "elapsed_time": 600},
                {"id": 7, "start_date": "2026-10-25T08:00:00Z", "elapsed_time": 600},
                {"id": 8, "start_date": "2026-10-24T08:00:00Z", "elapsed_time": 600}]


@pytest.fixture
def stubs(monkeypatch):
    acts = [Activity(i, n, "road_biking", "", 1.4, (FIX / f"{f}.gpx").read_text())
            for i, n, f in [(1, "Morning Ride", "morning"), (2, "Afternoon Ride", "afternoon")]]
    photos_added = []
    monkeypatch.setattr(app_mod.garmin, "login", lambda d: object())
    monkeypatch.setattr(app_mod.garmin, "find_activities", lambda c, s: [{}, {}])
    monkeypatch.setattr(app_mod.garmin, "download", lambda c, m: acts)
    monkeypatch.setattr(app_mod, "Strava", FakeStrava)
    monkeypatch.setattr(app_mod.strava_web, "add_photos",
                        lambda d, aid, photos: photos_added.append((aid, photos)))
    FakeStrava.uploads, FakeStrava.updates = [], []
    return photos_added


def test_dry_run_sends_merged_gpx(tmp_path, stubs):
    ctx = FakeCtx(tmp_path, "dry today | Test")
    app_mod.APP.handle(ctx)
    assert len(ctx.files) == 1 and ctx.files[0].count("<trkseg>") == 2
    assert FakeStrava.uploads == []


def test_full_run(tmp_path, stubs):
    photo = tmp_path / "p.jpg"
    photo.write_bytes(b"x")
    ctx = FakeCtx(tmp_path, "today | Lake loop | Windy", [photo])
    app_mod.APP.handle(ctx)
    gpx, name, desc, ext = FakeStrava.uploads[0]
    assert (name, desc) == ("Lake loop", "Windy") and ext.startswith("garmin-")
    assert FakeStrava.updates == [(42, {"sport_type": "Ride"})]
    assert stubs == [(42, [photo])]
    final = ctx.messages[-1]
    assert "strava.com/activities/42" in final
    assert "activities/7" in final and "activities/8" not in final   # only overlapping ones
    assert "1 photo(s) added" in final


def test_photo_failure_does_not_fail_run(tmp_path, stubs, monkeypatch):
    def boom(*a):
        raise RuntimeError("session expired")
    monkeypatch.setattr(app_mod.strava_web, "add_photos", boom)
    ctx = FakeCtx(tmp_path, "today", [tmp_path / "p.jpg"])
    app_mod.APP.handle(ctx)
    assert "Photos failed (session expired)" in ctx.messages[-1]


def test_duplicate_upload_updates_existing_activity(tmp_path, stubs, monkeypatch):
    monkeypatch.setattr(FakeStrava, "upload_gpx",
                        lambda self, *a: (FakeStrava.uploads.append(a), (99, True))[1])
    ctx = FakeCtx(tmp_path, "today | New title | New desc")
    app_mod.APP.handle(ctx)
    assert FakeStrava.updates == [
        (99, {"sport_type": "Ride", "name": "New title", "description": "New desc"})]
    assert "updated it" in ctx.messages[-1]
