# Fair Weather

A single-page weather summary for the places you follow.

- **Places:** Minsk, Warsaw, Dublin and New York by default. Add any city with the search box, remove with ×.
- **Timeline:** Today (hourly), 3, 7 or 14 days.
- **Units:** °C / °F.
- **Theme:** follows your device by default; the sun/moon button switches between light and dark.
- Your choices (places, timeline, units, theme) are remembered in the browser (localStorage).

## Data source

**Daily conditions** are worked out from the daytime hours (7:00–19:00), not from Open-Meteo's
daily code, which reports the single most severe hour. Rain, snow, storms or fog count only if
they last at least two daytime hours; otherwise the label comes from average cloud cover, using
the US National Weather Service terms (Sunny ≤12%, Mostly sunny ≤37%, Partly cloudy ≤62%,
Mostly cloudy ≤87%, Cloudy).

Forecasts come from [Open-Meteo](https://open-meteo.com/), a free, key-less API that
blends national weather service models (ECMWF, DWD, NOAA, Météo-France and others).
City search uses the Open-Meteo geocoding API. The page fetches directly from the
browser and refreshes every 30 minutes while open.

## Run locally

It's one static file with no build step:

```bash
python3 -m http.server -d weather 8000
```

Then open http://localhost:8000.

## Deploy

`.github/workflows/deploy-weather.yml` publishes the `weather/` folder to GitHub Pages
on every push to `main` (or manually via *Run workflow*). One-time setup:
**Settings → Pages → Build and deployment → Source: GitHub Actions**.
