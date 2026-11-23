# Watches the board's chip temperature: notes it in the log every 10 minutes and says once when it's running hot (the
# wall already eases its animation from 80 °C, and 90 °C switches the board off)
import datetime
import logging
import threading
import time
from nestor.wall import chip_temperature
CHECK_SECONDS = 60
LOG_EVERY_SECONDS = 600
WARN_CELSIUS = 85  # This hot, Nestor says so (once until it has cooled down)
CALM_CELSIUS = 78  # Down to this, the next hot spell is warned about again
WARNING_FRESH_MINUTES = 30  # A warning held through quiet hours is dropped after this long
log = logging.getLogger(__name__)

# The watcher, running in the background for the life of the service (only where there's a chip temperature)
class HeatWatcher:
    # Start watching
    def __init__(self, announcer, settings):
        self.announcer = announcer
        self.warn_at = int(settings.get("heat_warning", WARN_CELSIUS))
        self.warned = False
        self.hottest = None  # The hottest reading since the last log note
        threading.Thread(target=self.run, name="heat-watch", daemon=True).start()

    # Read the temperature every minute
    def run(self):
        last_note = 0.0

        # For the life of the service
        while True:
            celsius = chip_temperature()

            # A PC has no chip temperature to watch
            if celsius is None:
                return
            self.hottest = max(self.hottest or celsius, celsius)

            # Every 10 minutes, a note of the temperature now and the hottest since the last note
            if time.time() - last_note >= LOG_EVERY_SECONDS:
                log.info("The board is at %d °C (hottest in the last 10 minutes: %d °C)", celsius, self.hottest)
                last_note = time.time()
                self.hottest = None
            self.check(celsius)
            time.sleep(CHECK_SECONDS)

    # Warn once when it gets too hot, and get ready to warn again once it has cooled down
    def check(self, celsius):
        # Too hot for the first time in this spell, or cool again after one
        if celsius >= self.warn_at and not self.warned:
            self.warned = True
            log.warning("The board is running hot: %d °C (it switches off at 90 °C)", celsius)
            expires = (datetime.datetime.now() + datetime.timedelta(minutes=WARNING_FRESH_MINUTES)).isoformat()
            self.announcer.alert(f"The board's running hot, at {celsius} degrees. The wall is easing its animation "
                                 "to cool it down.", source="heat", expires=expires)
        elif celsius <= CALM_CELSIUS and self.warned:
            self.warned = False
            log.info("The board has cooled down to %d °C", celsius)
