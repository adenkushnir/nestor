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

## Status

Work in progress: milestone 1 (speaking) is done; the other features are on the way.
