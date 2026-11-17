# Wires the speaker, announcer, web server and watchers together into one running Nestor service
import logging
import socket
import threading
from werkzeug.serving import make_server
from nestor import tts
from nestor.announcer import Announcer
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

        # Reminders only fire in the full service, so a quick speak.py never speaks them twice
        if watchers:
            ReminderScheduler(self.announcer, settings)

        # GitHub alerts can be turned off in config.yaml
        if watchers and settings.get("github_watch", True):
            GitHubWatcher(self.announcer, settings)

    # Stop the web server and disconnect from the speaker
    def stop(self):
        self.web_server.shutdown()
        self.speaker.disconnect()
