# Turns names, durations, times and dates into words that sound right when spoken
import datetime
import os

# Say a folder or repo name out loud: the spoken_names setting first, otherwise hyphens and underscores become spaces
def spoken_name(raw_name, settings):
    spoken_names = settings.get("spoken_names") or {}

    # Use the user's own name for it when there is one
    if raw_name in spoken_names:
        return spoken_names[raw_name]
    return raw_name.replace("-", " ").replace("_", " ")

# Spoken name of the project a folder belongs to, e.g. "C:\Vibes\Fencing" -> "Red Piste" via spoken_names
def spoken_project(folder, settings):
    return spoken_name(os.path.basename(os.path.normpath(folder)), settings)

# Turn seconds into words like "45 seconds", "3 minutes" or "1 hour 20 minutes"
def spoken_duration(seconds):
    # Under a minute, count seconds
    if seconds < 60:
        return f"{round(seconds)} seconds"
    minutes = round(seconds / 60)

    # Under an hour, count minutes
    if minutes < 60:
        return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"
    hours, minutes = divmod(minutes, 60)
    hour_words = f"{hours} hour" if hours == 1 else f"{hours} hours"

    # Leave out "0 minutes"
    if minutes == 0:
        return hour_words
    return f"{hour_words} {minutes} minutes" if minutes != 1 else f"{hour_words} 1 minute"

# Say a clock time the US way: "6 PM", "6:30 PM", "noon", "midnight"
def spoken_clock(clock):
    # The two times with names of their own
    if (clock.hour, clock.minute) == (12, 0):
        return "noon"
    elif (clock.hour, clock.minute) == (0, 0):
        return "midnight"
    hour = clock.hour % 12 or 12
    half = "AM" if clock.hour < 12 else "PM"
    return f"{hour} {half}" if clock.minute == 0 else f"{hour}:{clock.minute:02d} {half}"

# Say a date relative to today: "today", "tomorrow", "Friday" (within a week), else "December 3"
def spoken_day(date, today):
    days_ahead = (date - today).days

    # Close dates get words, later ones the month and day
    if days_ahead == 0:
        return "today"
    elif days_ahead == 1:
        return "tomorrow"
    elif 1 < days_ahead < 7:
        return date.strftime("%A")
    else:
        return f"{date.strftime('%B')} {date.day}"

# Say a moment relative to now, e.g. "tomorrow at 9:30 AM"
def spoken_moment(moment, now=None):
    now = now or datetime.datetime.now()
    return f"{spoken_day(moment.date(), now.date())} at {spoken_clock(moment.time())}"

# Say a "HH:MM" time (as stored in JSON), e.g. "16:42" -> "4:42 PM"
def spoken_hhmm(hhmm):
    return spoken_clock(datetime.time(int(hhmm[:2]), int(hhmm[3:5])))

# Join items the way people list them: "a", "a and b", "a, b, and c"
def spoken_list(items):
    # Short lists need no commas
    if len(items) < 3:
        return " and ".join(items)
    return ", ".join(items[:-1]) + ", and " + items[-1]
