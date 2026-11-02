# flipper_apps

A collection of small apps you write yourself, in the spirit of Flipper Zero apps, all reachable from one **Telegram bot**. The bot is the gateway: each app is one command, and the bot routes `/command` messages to it, along with any text and photos. Adding an app means dropping a folder into `apps/`.

The gateway talks to the official [Telegram Bot API](https://core.telegram.org/bots/api) directly with `httpx` and long polling, so it needs no bot framework, webhook or public URL.

| Command | What it does |
|---|---|
| `/help` | Lists the commands, or shows the usage of one: `/help garmin_to_strava` |
| `/ping` | Example app that replies with `pong` |
| [`/garmin_to_strava`](apps/garmin_to_strava/README.md) | Merges Garmin activities and uploads them to Strava |

Each app has its own README with its usage and setup:
- [`/garmin_to_strava`](apps/garmin_to_strava/README.md)

**Setup overview**
1. [Create the Telegram bot](#1-create-the-telegram-bot)
2. [Install](#2-install): a Python venv, or Docker only
3. [Set up the apps](#3-set-up-the-apps), such as connecting accounts
4. [Try it](#4-try-it)
5. [Deploy (always on)](#5-deploy-always-on)
6. [Update](#6-update) to the latest code

## Layout
```
bot/        the Telegram gateway: Bot API client, App base class, app discovery, polling runner
apps/       your apps, one package each, exporting APP = SomeApp()
tests/
```

## Adding an app
1. Create `apps/my_app/__init__.py`:
   ```python
   from bot.app import App, Context

   class MyApp(App):
       command = "my_app"            # a-z, 0-9, _ only (Telegram rule)
       description = "Shown in /help and in the command menu"
       usage = "/my_app <args> — longer help"

       def handle(self, ctx: Context) -> None:
           msg = ctx.reply("working…")
           ctx.edit(msg, f"done: {ctx.text}, {len(ctx.photos)} photos")

   APP = MyApp()
   ```
2. Optionally add `apps/my_app/README.md` with its usage and setup, and link it in the lists above.
3. Restart the bot. The app is discovered automatically and the Telegram command menu is updated.

`ctx` gives each call:
- `text`: everything after the command.
- `photos` / `documents`: downloaded files. All photos of an album are collected into one call, and images sent "as file" count as photos.
- `reply` / `edit` / `send_file`.
- `ask(prompt, secret=False)`: ask the user a question and wait for their reply. With `secret=True`, the reply is deleted from the chat right after reading, which is useful for passwords. If the user sends `/cancel` or another command, or doesn't answer within 5 minutes, it raises `AskCancelled`, and the bot reports the call as cancelled.
- `user_dir`: persistent and private to the calling Telegram user, at `data/<command>/users/<telegram_user_id>/`. Keep anything user-specific here, such as logins.
- `data_dir`: persistent and shared by all users of the app, at `data/<command>/`.
- `work_dir`: temporary, deleted after the call.

Each call runs in its own thread. If an app raises an exception, the error is reported in the chat.

## 1. Create the Telegram bot
1. In Telegram, open [@BotFather](https://t.me/BotFather) and send `/newbot`.
2. Choose a display name (for example "Flipper Apps") and a username that ends in `bot` (for example `my_flipper_apps_bot`).
3. BotFather replies with a token like `123456789:AAH…`. You'll put it in `.env` as `TELEGRAM_TOKEN` in step 2. Keep it secret: anyone with it can control the bot. If it leaks, send `/revoke` to BotFather to get a new one.
4. Message [@userinfobot](https://t.me/userinfobot) to get your numeric user id. It goes in `.env` as `ALLOWED_USER_IDS`, and the bot ignores everyone not listed there.
5. Open a chat with your new bot and press **Start**. Bots can't message you first.

You don't need to set up the command menu: the gateway registers every app's command with Telegram (`setMyCommands`) each time it starts. For testing, a second bot with its own token keeps your everyday bot untouched.

## 2. Install
All commands in this README run inside the `flipper_apps/` folder. There are two ways to install, and you can use both:
- **Python venv**: for running and testing on your own computer.
- **Docker only**: for an always-on server. The image brings its own Python 3.12, so the server's Python version doesn't matter.

### Python venv
Needs **Python 3.11+**. Check with `python3 --version`.

**Option A: your `python3` is already 3.11 or newer**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
playwright install chromium   # headless browser, used by /garmin_to_strava for strava.com
```

**Option B: your Python is older (for example 3.6 on Ubuntu 18.04)**

Install a newer Python next to the system one with [uv](https://docs.astral.sh/uv/). It needs no `sudo`. Don't replace the system `python3`, because the OS depends on it.
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # then open a new terminal
uv venv -p 3.12                                   # downloads Python 3.12 if needed
source .venv/bin/activate
python --version                                  # should print 3.12.x
uv pip install -r requirements.txt
playwright install chromium                       # headless browser, used by /garmin_to_strava for strava.com
```
Run `source .venv/bin/activate` again in every new terminal before using `python`.

### Docker only
**Requirements:**
- [Docker](https://docs.docker.com/engine/install/).
- About 1 GB of free disk space (check with `df -h`). The image is roughly 800 MB, most of it the headless browser `/garmin_to_strava` uses for strava.com. Each update builds a new image, so remove old ones with `docker image prune -f`.
- On a Raspberry Pi, a 64-bit OS: `uname -m` must print `aarch64`.

**Choose your Compose command.** Docker Compose comes in two forms, and you only need the one that works on your machine:
```bash
docker compose version     # Compose v2 plugin (newer Docker)
docker-compose version     # standalone Compose (older setups)
```
Use the first one that prints a version. Then define the `dc` shortcut that **every Docker command in this README uses**:
```bash
alias dc='docker compose'      # if the first one worked
alias dc='docker-compose'      # if only the second one worked
```
To keep the shortcut in new terminals, add the same alias line to `~/.bashrc` (or `~/.zshrc`), for example `echo "alias dc='docker-compose'" >> ~/.bashrc`.

If you see `unknown shorthand flag: 'd' in -d`, you used `docker compose` but the v2 plugin isn't installed. Use `docker-compose` instead, or install the plugin with `sudo apt-get install docker-compose-plugin`.

**Build the image:**
```bash
cp .env.example .env     # the build doesn't need it filled in yet, but Compose expects the file
dc build
```
Each setup command below has a Docker form, `dc run --rm bot <command>`. It runs the command once in a temporary container. Anything it saves lands in `./data` on the host, just as if you'd run it with Python.

### Configure `.env`
```bash
cp .env.example .env     # skip if you already did this above
```
Fill in `TELEGRAM_TOKEN` and `ALLOWED_USER_IDS` from step 1, and `TZ` (for example `Europe/Berlin`) so that "today" means your day. App-specific settings, if any, are described in each app's README.

## 3. Set up the apps
Apps that need an account ask you to log in or connect it in the chat the first time you use them, and remember it separately for each Telegram user. See each app's README, for example [`/garmin_to_strava`](apps/garmin_to_strava/README.md#accounts-and-logins).

**Privacy and passwords:**
- Each user's logins are stored separately, under their own Telegram user id, and app commands only ever show or change the caller's own data. The bot ignores everyone not in `ALLOWED_USER_IDS`.
- The bot only answers in one-to-one chats. In groups it ignores everything, because others would see its questions and it can't delete password replies there.
- Messages to a Telegram bot aren't end-to-end encrypted. They pass through Telegram's servers to wherever the bot runs.
- When an app asks for a password, the bot deletes your reply from the chat right after reading it.
- Apps keep only the login result, such as a token or browser cookies, never the password. It's stored in `data/` on the machine running the bot, readable only by the bot's user, so whoever runs the server can read it.
- Apps offer a command to forget your saved logins, for example `/garmin_to_strava forget all`.

## 4. Try it
Start the bot in the foreground and send it `/ping`. Then try your apps, for example `/garmin_to_strava today | Test` (see [its README](apps/garmin_to_strava/README.md#try-it)). Press Ctrl+C to stop the bot.
```bash
python -m bot      # Python venv
dc up              # Docker
```

## 5. Deploy (always on)
Run the bot with Docker on any always-on Linux machine, such as a ~€4/month VPS (Hetzner), a Raspberry Pi or Fly.io with a volume. You need the "Docker only" part of step 2 done, including the `dc` shortcut. `./data` is mounted into the container and holds all tokens and sessions.

### Start the bot
```bash
dc up -d --build      # build the image and start it in the background
dc logs -f            # wait for "polling; commands: …", then Ctrl+C
```
Then send `/ping` to the bot in Telegram.

### Everyday commands
| Task | Command |
|---|---|
| Is it running? | `dc ps`: `Up` means running, `Restarting` means it keeps crashing (check the logs) |
| Follow the logs | `dc logs -f` (Ctrl+C stops following; the bot keeps running) |
| Last 100 log lines | `dc logs --tail 100` |
| Stop | `dc stop`. It stays stopped, even after a reboot, until you start it again. |
| Start again | `dc start` |
| Restart | `dc restart` |
| Apply changes to `.env` | `dc up -d`. A plain `restart` keeps the old settings. |
| Update to the latest code | `git pull && dc up -d --build` (details in [6. Update](#6-update)) |
| Remove the container | `dc down`. Saved logins in `data/` are kept, and `dc up -d` brings it back. |

The logs never contain your bot token or passwords, so they're safe to share when asking for help.

### What happens on errors
- **An error inside one app**, such as Garmin being unreachable, is reported to you in the chat. The bot keeps running.
- **Network or Telegram outages** don't stop the bot. It waits and retries on its own.
- **If the bot process itself dies**, for example from a bad config or running out of memory, Docker starts it again automatically. That's because of `restart: unless-stopped` in `docker-compose.yml`. If it keeps crashing, Docker waits longer between attempts.
- **A config mistake**, such as an empty `TELEGRAM_TOKEN`, makes it crash on every start. `dc ps` then shows `Restarting`, and `dc logs --tail 20` shows the reason. Fix `.env`, then run `dc up -d`.
- **A bot you stopped yourself** with `dc stop` is never restarted automatically.

### Starting automatically after a server reboot
The container comes back after a reboot as long as the Docker service itself starts at boot. Enable that once:
```bash
sudo systemctl enable docker
systemctl is-enabled docker     # should print "enabled"
```
To test it, run `sudo reboot`, then `dc ps` after the machine is back. If you stopped the bot with `dc stop` before the reboot, it stays stopped.

### Troubleshooting: `no space left on device`
The build needs some temporary space. Check what's using it and remove unused Docker data:
```bash
df -h                      # free space per disk
docker system df           # space used by Docker
docker system prune -a     # remove unused images, stopped containers, build cache
docker builder prune -a    # remove the remaining build cache
```
Then run `dc up -d --build` again.

### Troubleshooting: `permission denied` reading `data/…` during the build
For example: `no permission to read from … data/garmin_to_strava/users/…/garmin_account.json`. Your copy of the code is from before this was fixed: it sent the `data/` folder to the Docker build, and the saved logins in it are readable only by root. Get the fix and build again:
```bash
git pull
dc up -d --build
```
Your saved logins in `data/` stay where they are and keep working.

## 6. Update
Your `.env` and `data/` (all saved logins) aren't part of git, so updating never touches them. Run everything inside the `flipper_apps/` folder.

### 1. Check which branch you're on
```bash
git branch --show-current
```
Until the pull request is merged, the code lives on the `claude/brave-davinci-59syio` branch. After it's merged, switch to `main` once and stay there:
```bash
git switch main
```

### 2. See what's new (optional)
```bash
git fetch
git log --oneline HEAD..@{u}     # commits you don't have yet
```

### 3. Get the new code
```bash
git pull
```
If git refuses because you changed files yourself, run `git status` to see which ones. Then either undo your changes with `git restore <file>`, or set them aside with `git stash`, pull, and bring them back with `git stash pop`.

### 4. Check for new settings
```bash
git diff HEAD@{1} -- .env.example    # what changed in the settings template with this pull
```
If new variables appear, add them to your `.env`. No output means nothing changed.

### 5. Restart with the new code
**Docker:**
```bash
dc up -d --build        # rebuild the image and replace the running container
dc logs -f              # wait for "polling; commands: …", then Ctrl+C
docker image prune -f   # optional: delete the old image to free disk space
```
A plain `dc restart` is **not** enough: it restarts the old image without the new code.

**Python venv:**
```bash
source .venv/bin/activate
python -m pip install -r requirements.txt     # or: uv pip install -r requirements.txt
playwright install chromium                   # in case the browser version changed
python -m bot                                 # stop the old one with Ctrl+C first
```

Then send `/ping` to the bot to check that it's running.

### Going back to the previous version
If the update breaks something, go back to the version you had before the pull, rebuild, and tell whoever maintains the code what went wrong:
```bash
git log --oneline -5            # find the commit you were on
git switch --detach <commit>    # for example: git switch --detach 3cffb4e
dc up -d --build
```
To return to the latest code later, run `git switch <branch>` (for example `git switch main`), then repeat step 5.
