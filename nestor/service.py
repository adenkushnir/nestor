# Wires the speaker, announcer, web server and watchers together into one running Nestor service
import logging
import socket
import threading
from werkzeug.serving import make_server
from nestor import tts
from nestor.announcer import Announcer
from nestor.config import load_secrets
from nestor.discovery import Advertiser
from nestor.event_alerts import EventAlerts
from nestor.github_watch import GitHubWatcher
from nestor.reminders import ReminderScheduler
from nestor.server import create_app
from nestor.speaker import Speaker
log = logging.getLogger(__name__)

# Find this computer's IP address on the network that leads to the speaker
def lan_ip_towards(host):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect((host, 8009))  # UDP connect sends nothing; it just picks the right network
        return probe.getsockname()[0]

# The running service: connected speaker, announcer, web server in a background thread, and optional watchers
class Service:
    # Connect to the speaker and start the web server; watchers only run in the full service, not for speak.py
    def __init__(self, settings, watchers=False):
        tts.clean_cache()
        self.speaker = Speaker(settings.get("speaker_name"), settings.get("speaker_host"))
        port = int(settings.get("port", 8765))
        base_url = f"http://{lan_ip_towards(self.speaker.host)}:{port}"
        self.announcer = Announcer(self.speaker, settings, base_url)
        self.web_server = make_server("0.0.0.0", port, create_app(self.announcer, settings), threaded=True)
        self.web_thread = threading.Thread(target=self.web_server.serve_forever, name="web", daemon=True)
        self.web_thread.start()
        log.info("Web server on %s", base_url)
        self.advertiser = None

        # Only the full service tells Datebook where it is; a failure there doesn't stop Nestor
        if watchers:
            # Announce on the same network as the speaker
            try:
                self.advertiser = Advertiser(lan_ip_towards(self.speaker.host), port)
            except Exception as error:
                log.warning("Datebook won't be able to find Nestor on the network: %s", error)

        # Reminders and event heads-ups only fire in the full service, so a quick speak.py never speaks them twice
        if watchers:
            ReminderScheduler(self.announcer, settings)
            EventAlerts(self.announcer, settings)

        # GitHub alerts can be turned off in config.yaml
        if watchers and settings.get("github_watch", True):
            GitHubWatcher(self.announcer, settings)

        # Hey John runs in the full service once its keys and wake word file are in place
        if watchers and settings.get("john", True):
            self.start_john(settings)

    # Start Hey John, or log what's missing for it (the rest of Nestor runs either way)
    def start_john(self, settings):
        from nestor.john import John  # Imported only here: speech-to-text is slow to load, and speak.py doesn't need it
        from nestor.john import missing_setup
        secrets = load_secrets()
        problems = missing_setup(settings, secrets)

        # John needs his keys and wake word first
        if problems:
            log.info("Hey John is off until these are set up: %s", "; ".join(problems))
            return
        John(self.announcer, settings, secrets)

    # Stop the web server and network announcement, and disconnect from the speaker
    def stop(self):
        # Only the full service announces itself
        if self.advertiser:
            self.advertiser.stop()
        self.web_server.shutdown()
        self.speaker.disconnect()
