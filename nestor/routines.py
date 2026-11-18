# "Start my day" (ends the sleeping period, gives the day ahead, then plays what was held overnight) and "goodnight"
# (previews tomorrow, then starts the sleeping period); used by Hey John and the API
from nestor import govee
from nestor.briefing import build_briefing
from nestor.spoken import spoken_clock

# End the sleeping period now, speak the day ahead, then play the alerts held overnight; returns the briefing data
def start_my_day(announcer, settings):
    announcer.quiet_hours.wake_up()

    # The lights rise like the sun while the day ahead is read
    if govee.lights:
        govee.lights.sunrise()
    briefing = build_briefing(settings, day="today")
    announcer.say(briefing["text"], with_chime=False)
    announcer.release_now()
    return briefing

# Speak tomorrow's preview and when quiet hours end, then start the sleeping period; returns the briefing data
def goodnight(announcer, settings):
    briefing = build_briefing(settings, day="tomorrow")
    until = announcer.quiet_hours.go_to_sleep()
    announcer.say([briefing["text"], f"Goodnight. I'll keep quiet until {spoken_clock(until.time())}."],
                  with_chime=False)

    # The lights fade out over a minute
    if govee.lights:
        govee.lights.goodnight()
    briefing["quiet_until"] = until.isoformat(timespec="seconds")
    return briefing
