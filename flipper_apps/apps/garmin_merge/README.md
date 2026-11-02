# `/garmin_merge`

Merges your Garmin activities into one and sends you the merged GPX file in Telegram. It's one of the [flipper_apps](../../README.md); set up the bot there first.

## Usage
Send `/garmin_merge help` (or just `/garmin_merge`) to see the short help in the chat. A bare command never merges anything.

To merge, send for example:
```
/garmin_merge today
/garmin_merge today | Morning ride to the lake
```
The bot then:
1. finds the matching Garmin Connect activities that have GPS and downloads each as GPX,
2. merges them into one track in time order, the same as [joewein gpxmerge](https://joewein.net/bike/gpxmerge/), with one segment per activity so apps like Strava count the gaps as paused time,
3. sends you the merged file, for example `2026-11-02_Morning_ride_to_the_lake.gpx`.

You can then upload the file wherever you like, for example on strava.com/upload/select.

**Selector** (the part before `|`): `today`, `yesterday`, `2026-10-24`, `last 2`, `last ride` (meaning the single most recent ride), `rides today`, `last 3 runs`, or `latest activities today`. Types are ride, run, walk, hike and swim.

**Title** (optional, after `|`): names the merged track and the file. Without `|`, the first line is the selector only if it names a day or `last`; otherwise it's the title and the selector is `today`. So `/garmin_merge Morning ride` merges today's activities into "Morning ride".

## Garmin login
On your first call, the bot asks for your Garmin Connect email and password, and the verification code Garmin sends you if your account uses two-step verification. Garmin offers no other way for personal accounts. Your password replies are deleted from the chat right after reading.

The bot never stores your password. It keeps only the Garmin login token, which lasts about a year and is renewed automatically, saved **separately for each Telegram user** in `data/garmin_merge/users/<telegram_user_id>/`. If the login stops working, the bot simply asks again. Send `/cancel` at any question to stop.

| Command | What it does |
|---|---|
| `/garmin_merge accounts` | Shows your connected Garmin account: name, email, when connected, and tokens masked like `abcd…wxyz` (never in full) |
| `/garmin_merge login` | Logs in to Garmin now (again). `connect` works too. |
| `/garmin_merge forget` | Deletes your saved Garmin login, after asking you to confirm. `logout` works too. |
| `/garmin_merge help` | Shows the short help |

These only ever show or change **your own** login.

## Try it from a terminal
You can also run the app without Telegram. It asks the same questions there and saves the login for your Telegram user id (the first of `ALLOWED_USER_IDS`, or `--user <id>`), so the bot reuses it. The merged file is saved in `data/garmin_merge/users/<id>/`. Run it from the `flipper_apps/` folder:
```bash
python -m apps.garmin_merge.cli "today | Test"                         # Python venv
dc run --rm bot python -m apps.garmin_merge.cli "today | Test"         # Docker
python -m apps.garmin_merge.cli accounts
```

## Caveats
- Garmin has no public API for personal accounts. This app uses the unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library, which can break when Garmin changes its login.
- Logins saved under the old `/garmin_to_strava` name aren't picked up; the bot simply asks for your Garmin login once more.
