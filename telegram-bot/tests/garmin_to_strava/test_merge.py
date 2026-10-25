from pathlib import Path

import gpxpy
import pytest

from apps.garmin_to_strava.merge import merge, summarize

FIX = Path(__file__).parent / "fixtures"


def load(*names):
    return [(FIX / f"{n}.gpx").read_text() for n in names]


def test_merge_orders_by_time_regardless_of_input_order():
    merged = merge(load("afternoon", "morning"), name="Day out")
    assert len(merged.tracks) == 1
    track = merged.tracks[0]
    assert track.name == "Day out"
    assert len(track.segments) == 2
    times = [p.time for seg in track.segments for p in seg.points]
    assert times == sorted(times)
    assert times[0].hour == 8 and times[-1].hour == 14


def test_merged_xml_roundtrips_with_extensions():
    xml = merge(load("morning", "afternoon")).to_xml()
    assert "TrackPointExtension" in xml and "<ns3:hr>140</ns3:hr>" in xml
    again = gpxpy.parse(xml)
    assert again.get_points_no() == 6
    assert again.tracks[0].type == "road_biking"


def test_summary_excludes_gap_between_activities():
    single = summarize(merge(load("morning")))
    both = summarize(merge(load("morning", "afternoon")))
    assert both.points == 6
    assert both.distance_km == pytest.approx(2 * single.distance_km, rel=0.01)
    assert both.elapsed.total_seconds() == 6 * 3600 + 10 * 60


def test_merge_rejects_empty():
    with pytest.raises(ValueError):
        merge([])
