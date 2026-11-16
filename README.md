# Nestor

Nestor makes a Google Nest Audio speaker do things Google Home can't do on its own. It runs as a Python app on a Windows
PC on the same Wi-Fi.

## Planned features

- **Speak anything** from a terminal (`python speak.py "dinner's ready"`) or from any program through a local web API.
- **Alerts** from your computer: Claude Code finished a task, a GitHub Actions run failed, a long command is done.
- **Reminders and a morning briefing** with weather, news, sunrise and sunset, and your Google Calendar.
- **"Hey Google" commands that run code on your PC**, such as focus mode and goodnight, using Google Home routines.
- **Auto-pause** of the speaker's music when you join a call on the PC.
- **Phone control panel** on your home Wi-Fi.
- **"Hey Claude" voice assistant**: the PC's microphone hears you, Claude answers out loud on the speaker, and it can set
  reminders, search the web and remember things.
- **Govee lights**: alert flashes, focus colours, goodnight fade.

## How it works

Nestor talks to the speaker over the Cast protocol on your local network (no Google account or cloud needed). It turns
text into speech with Microsoft Edge neural voices and serves the audio from the PC so the speaker can play it.

## Setup (Windows, Git Bash)

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m nestor --list-speakers
```

Copy `config.example.yaml` to `config.yaml` and set `speaker_name` to your speaker's name from the list. The first time
Nestor runs, Windows asks whether Python may use the network: allow it on **private** networks, because the speaker
fetches its audio from the PC.

## Use

Run the service, which keeps the speaker connection open so messages play quickly:

```bash
.venv/Scripts/python -m nestor
```

Make the speaker talk from any terminal:

```bash
.venv/Scripts/python speak.py "Dinner's ready"
```

If the service isn't running, `speak.py` connects to the speaker itself (a few seconds slower).

From any program on the PC or your home network:

```bash
curl -X POST http://localhost:8765/speak -H "Content-Type: application/json" -d '{"text": "Backup finished"}'
```

Add `"wait": true` to get the reply only after the message has been spoken. Note that anyone on your home Wi-Fi can
reach this API.

Nestor plays a chime, speaks at `announce_volume`, then puts the volume back. Audio that was playing in the speaker's
built-in media player resumes. Music from apps like Spotify stops and has to be restarted by hand.

## Alerts

Alerts are announcements from your computer. Unlike `speak.py`, they respect **quiet hours** (`quiet_hours` in
`config.yaml`, 22:00–08:00 by default). Alerts that arrive at night are saved and played when quiet hours end, starting
with "While you were asleep, 3 messages came in."

Any program can send one:

```bash
curl -X POST http://localhost:8765/alert -H "Content-Type: application/json" -d '{"text": "Backup finished"}'
```

### Long commands: tell.py

`tell.py` runs a command, then says whether it worked and how long it took ("Train finished after 12 minutes", or
"Build failed after 40 seconds, with exit code 1"):

```bash
.venv/Scripts/python tell.py python train.py --epochs 50
.venv/Scripts/python tell.py --name "The export" ./export.sh
```

To use it from any folder as just `tell`, add this line to `~/.bashrc` (Git Bash):

```bash
alias tell='"/c/Vibes/Google Home/.venv/Scripts/python" "/c/Vibes/Google Home/tell.py"'
```

### Claude Code

`hooks/claude_code.py` makes the speaker say "Claude finished in Red Piste after 4 minutes" when a Claude Code reply took
longer than `claude_min_minutes` (1 by default). Shorter replies stay silent. Add it to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "\"C:/Vibes/Google Home/.venv/Scripts/python.exe\" \"C:/Vibes/Google Home/hooks/claude_code.py\""}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "\"C:/Vibes/Google Home/.venv/Scripts/python.exe\" \"C:/Vibes/Google Home/hooks/claude_code.py\""}]}]
  }
}
```

The hook prints nothing and always succeeds, so it never gets in Claude Code's way, even when Nestor isn't running.

### GitHub

While `python -m nestor` runs, it checks your GitHub repos every 5 minutes and announces:

- a CI check that fails ("The Android check failed on Datebook"), and when it passes again;
- new stars;
- new issues and pull requests opened by other people (not you, and not bots).

It uses the GitHub CLI's login (`gh auth login`), so Nestor stores no token. The first check after setup only records
what is already there. Turn it off with `github_watch: false`.

`spoken_names` in `config.yaml` sets how folder, repo and branch names are said, e.g. `"red-piste": "Red Piste"`.

## Reminders

Each reminder is spoken twice: a heads-up 15 minutes before ("In 15 minutes: call mum.") and again at its time
("Reminder: call mum."). Reminders are alerts, so during quiet hours they are held until morning; `remind` warns you
when that will happen. Nestor must be running at the time for a reminder to be spoken.

One-off reminders, with the time at the start or the end:

```bash
.venv/Scripts/python remind.py 18:00 call mum
.venv/Scripts/python remind.py tomorrow 9:30 dentist
.venv/Scripts/python remind.py take the pizza out in 20m
.venv/Scripts/python remind.py fri 7pm dinner with Sam
.venv/Scripts/python remind.py 12/3 2pm haircut
```

Repeating reminders go in `reminders.yaml` (copy `reminders.example.yaml`). Nestor rereads it on every check, so edits
work without a restart:

```yaml
- text: Fencing training
  days: [tue, thu]     # or daily, weekdays, weekends, sun
  time: "18:00"
```

## Briefing

```bash
.venv/Scripts/python briefing.py          # speak it now
.venv/Scripts/python briefing.py --show   # just print it
.venv/Scripts/python briefing.py --json   # the data behind it
```

The briefing gives the date, the weather (Open-Meteo, free, no key), sunrise and sunset, today's reminders, and GitHub
news from overnight. Set `home_location` in `config.yaml` to `"Town, ST"`, a ZIP code or `"lat,lon"` for the weather.

To use `remind` and `briefing` from any folder, add these to `~/.bashrc`:

```bash
alias remind='"/c/Vibes/Google Home/.venv/Scripts/python" "/c/Vibes/Google Home/remind.py"'
alias briefing='"/c/Vibes/Google Home/.venv/Scripts/python" "/c/Vibes/Google Home/briefing.py"'
```

## API

Nestor's web server (port 8765, home network only) is also how the phone page, Datebook and the wall display talk to
it. Everything is JSON.

| Request | What it does |
|---|---|
| `POST /speak` `{"text", "wait"}` | Speak straight away |
| `POST /alert` `{"text", "source"}` | Speak an alert (held during quiet hours) |
| `GET /alerts?limit=20` | Recent alerts, newest first |
| `GET /reminders` | One-off, repeating and today's reminders |
| `POST /reminders` `{"text", "at"}` or `{"text", "when": "tomorrow 6pm"}` | Add a one-off reminder |
| `DELETE /reminders/<id>` | Delete a one-off reminder |
| `GET /briefing` | The briefing as data and text |
| `POST /briefing` `{"wait"}` | Speak the briefing |
| `GET /health` | Is Nestor running, and which speaker |

## Status

Milestones 1 (speaking), 2 (alerts) and 3 (reminders and briefing) are done; the other features are on the way.
