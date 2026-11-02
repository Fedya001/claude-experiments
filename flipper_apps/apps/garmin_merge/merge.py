"""Merges several GPX files into one track, like https://joewein.net/bike/gpxmerge/.

All tracks end up in a single <trk>, one <trkseg> per original segment, ordered
by time, so apps like Strava count the gaps between activities as paused time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import gpxpy
import gpxpy.gpx


@dataclass
class Summary:
    points: int
    distance_km: float
    start: datetime | None
    end: datetime | None

    @property
    def elapsed(self) -> timedelta | None:
        return self.end - self.start if self.start and self.end else None


def _first_time(gpx: gpxpy.gpx.GPX) -> datetime:
    bounds = gpx.get_time_bounds()
    return bounds.start_time or datetime.max.replace(tzinfo=None)


def merge(gpx_texts: list[str], name: str | None = None) -> gpxpy.gpx.GPX:
    if not gpx_texts:
        raise ValueError("nothing to merge")
    parsed = sorted((gpxpy.parse(t) for t in gpx_texts),
                    key=lambda g: _first_time(g).replace(tzinfo=None))
    first = parsed[0]

    out = gpxpy.gpx.GPX()
    out.creator = first.creator
    out.time = first.time
    out.nsmap = {}
    for g in parsed:  # keep namespaces of heart rate / cadence extensions
        out.nsmap.update(g.nsmap)

    track = gpxpy.gpx.GPXTrack(name=name or (first.tracks[0].name if first.tracks else None))
    track.type = first.tracks[0].type if first.tracks else None
    for g in parsed:
        for t in g.tracks:
            for seg in t.segments:
                if seg.points:
                    track.segments.append(seg)
    if not track.segments:
        raise ValueError("the GPX files contain no track points")
    out.tracks.append(track)
    return out


def _utc(t: datetime | None) -> datetime | None:
    """GPX times are UTC by spec; make offset-less ones timezone-aware."""
    if t is None:
        return None
    return t.replace(tzinfo=timezone.utc) if t.utcoffset() is None else t.astimezone(timezone.utc)


def summarize(gpx: gpxpy.gpx.GPX) -> Summary:
    bounds = gpx.get_time_bounds()
    return Summary(points=gpx.get_points_no(), distance_km=gpx.length_2d() / 1000,
                   start=_utc(bounds.start_time), end=_utc(bounds.end_time))
