# `/garmin_to_strava`

Merges the day's Garmin activities into one and uploads it to Strava, with your title and description. It's one of the [flipper_apps](../../README.md); set up the bot there first.

## Usage
Send `/garmin_to_strava help` (or just `/garmin_to_strava`) to see the short help in the chat. A bare command never uploads anything.

To upload, send one message:
```
/garmin_to_strava today | Morning ride to the lake | Coffee stop at km 30
```
The bot then:
1. finds the matching Garmin Connect activities that have GPS and downloads each as GPX,
2. merges them into one track in time order, the same as [joewein gpxmerge](https://joewein.net/bike/gpxmerge/), with one segment per activity so the gaps count as paused time,
3. uploads the merged track to Strava and sets the title, description and sport type (taken from Garmin),
4. reports progress in a single message that it keeps editing, ending with the activity link.

**Photos:** Strava doesn't let apps add photos to activities; only Strava's partner apps can. Open the link the bot sends, which opens the activity in the Strava app, and add your photos there.

**Selector** (the part before the first `|`): `today`, `yesterday`, `2026-10-24`, `last 2`, `last ride` (meaning the single most recent ride), `rides today`, `last 3 runs`, or `latest activities today`. Types are ride, run, walk, hike and swim. If you leave out the `|` separators, the first line is the selector only if it names a day or `last`; otherwise it's the title and the selector is `today`. So a one-word title like `Ride` stays a title. After the title comes the description.

## One-time Strava API application
Whoever runs the bot does this once. The bot talks to Strava through Strava's official API, which needs a registered application:
1. Go to <https://www.strava.com/settings/api> and create an application:
   - **Application Name**: anything, for example "Flipper Apps".
   - **Category**: for example "Data Importer".
   - **Website**: anything, for example `http://localhost`.
   - **Authorization Callback Domain**: `localhost`.
2. Copy **Client ID** and **Client Secret** into `.env` as `STRAVA_CLIENT_ID` and `STRAVA_CLIENT_SECRET`.
3. Restart the bot so it reads them (with Docker: `dc up -d`).

A new Strava application can connect only 1 Strava account until Strava reviews it. That's enough for personal use. If other people will use the bot too, request a review from that same settings page.

## Accounts and logins
The bot asks the first time it needs each account:
- **Garmin**, on your first call: your Garmin Connect email and password, and the verification code Garmin sends you if your account uses two-step verification. Garmin offers no other way for personal accounts. Your password replies are deleted from the chat right after reading.
- **Strava**, on your first upload: the bot sends Strava's official authorization link.
  1. Tap the link and sign in to Strava the way you always do. **Google or Apple sign-in works**, because you sign in on Strava itself and the bot never sees it.
  2. Tap **Authorize**, keeping the permission to upload activities ticked.
  3. You land on a page that fails to load (its address starts with `http://localhost`). That's expected: copy the page's address from the address bar and paste it into the chat.

The bot never stores passwords. It keeps only the login results (the Garmin token and the Strava authorization), which are renewed automatically. They're saved **separately for each Telegram user** in `data/garmin_to_strava/users/<telegram_user_id>/`. If a login stops working, for example because you removed the bot's access in Strava's settings, the bot asks again. Send `/cancel` at any question to stop.

Manage your logins with these commands. They only ever show or change **your own** data:

| Command | What it does |
|---|---|
| `/garmin_to_strava accounts` | Shows your connected Garmin and Strava accounts: names, when connected, Strava permissions, and tokens masked like `abcd…wxyz` (never in full) |
| `/garmin_to_strava login garmin` | Logs in to Garmin now (again), without uploading anything. Same with `strava`. `connect` works too. |
| `/garmin_to_strava forget garmin` | Deletes your saved Garmin login, after asking you to confirm. Also works with `strava` (this also revokes the bot's access in your Strava account) or `all`. `logout` works too. |
| `/garmin_to_strava help` | Shows the short help |

**Turn off Garmin → Strava auto-sync** in Garmin Connect. Otherwise each activity is also on Strava separately. The bot lists any overlapping Strava activities so you can delete them in Strava.

## Try it
Send `/garmin_to_strava today | Test`. The first time, the bot asks for your Garmin login and then sends the Strava link. Then it uploads the activity and replies with its link. You can rename or delete the test activity in Strava afterwards.

You can also run the app in a terminal, without Telegram. It asks the same questions there and saves the logins for your Telegram user id (the first of `ALLOWED_USER_IDS`, or `--user <id>`), so the bot reuses them. Run it from the `flipper_apps/` folder:
```bash
python -m apps.garmin_to_strava.cli "today | Test"                         # Python venv
dc run --rm bot python -m apps.garmin_to_strava.cli "today | Test"         # Docker
python -m apps.garmin_to_strava.cli accounts
```

## Caveats
- Garmin has no public API for personal accounts. This app uses the unofficial [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library, which can break when Garmin changes its login.
- Strava can't receive photos from apps (see [Usage](#usage)). Add them in the Strava app.
