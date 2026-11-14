# Turns names and durations into words that sound right when spoken
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
