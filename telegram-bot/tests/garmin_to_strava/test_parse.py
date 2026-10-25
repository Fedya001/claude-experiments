from datetime import date

import pytest

from apps.garmin_to_strava.parse import Selector, SelectorError, parse_request, parse_selector

TODAY = date(2026, 10, 25)


@pytest.mark.parametrize("text,expected", [
    ("today", Selector(TODAY, TODAY)),
    ("", Selector(TODAY, TODAY)),
    ("latest activities today", Selector(TODAY, TODAY)),
    ("yesterday", Selector(date(2026, 10, 24), date(2026, 10, 24))),
    ("2026-10-20", Selector(date(2026, 10, 20), date(2026, 10, 20))),
    ("rides today", Selector(TODAY, TODAY, family="ride")),
    ("last 2", Selector(limit=2)),
    ("last 3 runs yesterday", Selector(date(2026, 10, 24), date(2026, 10, 24), 3, "run")),
])
def test_selector(text, expected):
    assert parse_selector(text, TODAY) == expected


@pytest.mark.parametrize("text", ["tomorrowish", "2026-13-01", "last 0"])
def test_selector_errors(text):
    with pytest.raises(SelectorError):
        parse_selector(text, TODAY)


def test_pipes():
    r = parse_request("yesterday | Morning ride | Coffee at km 30", TODAY)
    assert r.selector.date_from == date(2026, 10, 24)
    assert (r.title, r.description, r.dry_run) == ("Morning ride", "Coffee at km 30", False)


def test_dry_and_missing_parts():
    r = parse_request("dry today |", TODAY)
    assert r.dry_run and r.title is None and r.description is None


def test_lines_with_selector_first():
    r = parse_request("rides today\nLake loop\nWindy.\nGreat views.", TODAY)
    assert r.selector.family == "ride"
    assert r.title == "Lake loop" and r.description == "Windy.\nGreat views."


def test_lines_without_selector_default_to_today():
    r = parse_request("Lake loop\nWindy.", TODAY)
    assert r.selector == Selector(TODAY, TODAY)
    assert r.title == "Lake loop" and r.description == "Windy."


def test_empty_text():
    r = parse_request("", TODAY)
    assert r.selector == Selector(TODAY, TODAY) and r.title is None


def test_selector_matches_garmin_types():
    s = Selector(family="ride")
    assert s.matches_type("road_biking") and s.matches_type("gravel_cycling")
    assert not s.matches_type("running")
