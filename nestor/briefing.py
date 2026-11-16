# The briefing: greeting and date, weather, sunrise and sunset, today's reminders, and GitHub news from overnight.
# Built as data first (JSON for the API, the phone page and the wall display), then turned into spoken lines.
import datetime
import logging
from nestor import weather
from nestor.announcer import read_history
from nestor.reminders import todays_reminders
from nestor.spoken import spoken_hhmm
from nestor.spoken import spoken_list
OVERNIGHT_HOURS = 16
MAX_GITHUB_ITEMS = 3
log = logging.getLogger(__name__)

# "Good morning", "Good afternoon" or "Good evening" for the time of day
def greeting(now):
    # Morning until noon, afternoon until 6
    if now.hour < 12:
        return "Good morning"
    elif now.hour < 18:
        return "Good afternoon"
    else:
        return "Good evening"

# Texts of the GitHub alerts from the last 16 hours, oldest first
def overnight_github(now):
    since = (now - datetime.timedelta(hours=OVERNIGHT_HOURS)).isoformat(timespec="seconds")
    return [entry["text"] for entry in read_history() if entry["source"] == "github" and entry["time"] >= since]

# Build the briefing data, with its spoken lines and text at the end
def build_briefing(settings, now=None):
    now = now or datetime.datetime.now()
    data = {"generated": now.isoformat(timespec="seconds"), "date": now.date().isoformat(), "greeting": greeting(now),
            "weather": None, "weather_problem": None, "reminders": todays_reminders(now.date()),
            "github": overnight_github(now)}
    location = str(settings.get("home_location") or "").strip()

    # Weather needs a home location and the internet; without them the briefing goes on without it
    if not location:
        data["weather_problem"] = "home_location isn't set in config.yaml"
    else:
        # A failed lookup is noted, not fatal
        try:
            data["weather"] = weather.forecast(location, settings.get("temperature_unit", "fahrenheit"))
        except Exception as error:
            log.warning("No weather for the briefing: %s", error)
            data["weather_problem"] = str(error)
    data["lines"] = spoken_lines(data, now)
    data["text"] = " ".join(data["lines"])
    return data

# Turn the briefing data into the sentences Nestor says
def spoken_lines(data, now):
    lines = [f"{data['greeting']}. It's {now.strftime('%A')}, {now.strftime('%B')} {now.day}."]
    forecast = data["weather"]

    # Weather and sun times, when they could be fetched
    if forecast:
        lines.append(f"It's {forecast['now']} degrees and {forecast['conditions']}, with a high of "
                     f"{forecast['high']} and a low of {forecast['low']}.")

        # Rain only gets a mention when it's likely
        if forecast["rain_from"]:
            lines.append(f"Rain is likely from {spoken_hhmm(forecast['rain_from'])}.")
        clock_now = now.strftime("%H:%M")
        sunrise_tense = "was" if clock_now >= forecast["sunrise"] else "is"
        sunset_tense = "was" if clock_now >= forecast["sunset"] else "is"
        lines.append(f"Sunrise {sunrise_tense} at {spoken_hhmm(forecast['sunrise'])}, and sunset {sunset_tense} at "
                     f"{spoken_hhmm(forecast['sunset'])}.")

    # Today's reminders, if there are any
    if data["reminders"]:
        items = [f"{reminder['text']} at {spoken_hhmm(reminder['time'])}" for reminder in data["reminders"]]
        lines.append(f"Today: {spoken_list(items)}.")
    else:
        lines.append("No reminders today.")
    github_news = data["github"]

    # GitHub news from overnight, a few items at most
    if not github_news:
        lines.append("Nothing new on GitHub overnight.")
    elif len(github_news) <= MAX_GITHUB_ITEMS:
        lines.append("Overnight on GitHub: " + " ".join(github_news))
    else:
        extra_count = len(github_news) - MAX_GITHUB_ITEMS
        lines.append("Overnight on GitHub: " + " ".join(github_news[-MAX_GITHUB_ITEMS:]) +
                     f" And {extra_count} more.")
    return lines
