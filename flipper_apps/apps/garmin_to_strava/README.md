# `/garmin_to_strava`

Merges the day's Garmin activities into one and uploads it to Strava, with your title, description and photos. It's one of the [flipper_apps](../../README.md); set up the bot there first. There's nothing else to set up: the bot asks for your Garmin and Strava logins in the chat the first time you use it.

## Usage
Send one message with your photos attached, with the command in the caption:
```
/garmin_to_strava today | Morning ride to the lake | Coffee stop at km 30
```
The bot then:
1. finds the matching Garmin Connect activities that have GPS and downloads each as GPX,
2. merges them into one track in time order, the same as [joewein gpxmerge](https://joewein.net/bike/gpxmerge/), with one segment per activity so the gaps count as paused time,
3. uploads the merged track on strava.com and sets the title, description and sport type (taken from Garmin),
4. attaches your photos,
5. reports progress in a single message that it keeps editing, ending with the activity link.

**Selector** (the part before the first `|`): `today`, `yesterday`, `2026-10-24`, `last 2`, `last ride` (meaning the single most recent ride), `rides today`, `last 3 runs`, or `latest activities today`. Types are ride, run, walk, hike and swim. If you leave out the `|` separators, the first line is the selector only if it names a day or `last`; otherwise it's the title and the selector is `today`. So a one-word title like `Ride` stays a title. After the title comes the description.

## Accounts and logins
The first time a step needs an account, the bot asks for it in the chat:
- **Garmin**, on your first call: your Garmin Connect email and password, and the verification code Garmin sends you if your account uses two-step verification.
- **Strava**, on your first upload: your Strava email and password, and the code Strava emails you if it asks for one. If you sign in to Strava with Google or Apple, first set a Strava password in the Strava app (Settings → Account → Change password).

Your password replies are deleted from the chat right after reading. The bot never stores passwords. It keeps only the login result:
- the Garmin login token, which lasts about a year and is renewed automatically,
- the strava.com browser cookies.

These are saved **separately for each Telegram user** in `data/garmin_to_strava/users/<telegram_user_id>/`. When a login stops working, the bot simply asks again. Send `/cancel` at any question to stop.

Manage your logins with these commands. They only ever show or change **your own** data:

| Command | What it does |
|---|---|
| `/garmin_to_strava accounts` | Shows your connected Garmin and Strava accounts: name, email, when connected, and tokens masked like `abcd…wxyz` (never in full) |
| `/garmin_to_strava connect garmin` | Logs in to Garmin now (again), without uploading anything. Same with `strava`. |
| `/garmin_to_strava forget garmin` | Deletes your saved Garmin login, after asking you to confirm. Also works with `strava` or `all`. |

**Turn off Garmin → Strava auto-sync** in Garmin Connect. Otherwise each activity is also on Strava separately, and you'd have to delete those copies by hand.

## Try it
Send `/garmin_to_strava today | Test` with a photo attached. The first time, the bot asks for your Garmin login and then your Strava login. Then it uploads the activity and replies with its link. You can rename or delete the test activity in Strava afterwards.

You can also run the app in a terminal, without Telegram. It asks the same questions there and saves the logins for your Telegram user id (the first of `ALLOWED_USER_IDS`, or `--user <id>`), so the bot reuses them. Run it from the `flipper_apps/` folder:
```bash
python -m apps.garmin_to_strava.cli "today | Test" photo.jpg                     # Python venv
dc run --rm bot python -m apps.garmin_to_strava.cli "today | Test"                # Docker
python -m apps.garmin_to_strava.cli accounts
```

## Caveats
- Garmin has no public API for personal accounts. This app uses the unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library, which can break when Garmin changes its login.
- Strava's public API can't upload photos and needs a registered API application. So instead, this app does everything through the strava.com website in a headless browser. The page details it relies on are listed at the top of [`strava_web.py`](strava_web.py). If Strava changes its site, the bot reports which step failed. If only the photos fail, the activity is still uploaded and the bot tells you to add them in the Strava app.
- Strava may sometimes block automated logins, for example with a captcha. If that happens, the bot reports the login as failed.
- Telegram compresses photos sent the normal way. To keep full resolution, send them "as file".
