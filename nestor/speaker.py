# Finds the Google speaker on the network and plays audio on it over the Cast protocol
import logging
import time
import pychromecast
from pychromecast.controllers.media import MEDIA_PLAYER_STATE_BUFFERING
from pychromecast.controllers.media import MEDIA_PLAYER_STATE_IDLE
from pychromecast.controllers.media import MEDIA_PLAYER_STATE_PAUSED
from pychromecast.controllers.media import MEDIA_PLAYER_STATE_PLAYING
DEFAULT_MEDIA_RECEIVER = "CC1AD845"  # Cast app id of the built-in media player Nestor uses
ACTIVE_STATES = (MEDIA_PLAYER_STATE_PLAYING, MEDIA_PLAYER_STATE_BUFFERING)
log = logging.getLogger(__name__)

# Print every Cast device on the network (used once to find the speaker's name)
def list_speakers():
    browser = pychromecast.discovery.CastBrowser(pychromecast.discovery.SimpleCastListener(),
                                                 pychromecast.discovery.create_zeroconf())
    browser.start_discovery()
    time.sleep(8)
    browser.stop_discovery()
    device_infos = list(browser.devices.values())

    # Show each device's name, model and address
    for device_info in device_infos:
        print(f"{device_info.friendly_name}  ({device_info.model_name}, {device_info.host})")

    # Explain an empty result
    if not device_infos:
        print("No speakers found. Is the PC on the same Wi-Fi, and is Python allowed through the firewall?")

# Find the speaker named in the settings (or the only one on the network); returns it with its discovery browser,
# which must keep running while connected because the connection looks the speaker up through it
def find_cast(speaker_name, speaker_host):
    known_hosts = [speaker_host] if speaker_host else None

    # Look for the named speaker, or for all of them when no name is set
    if speaker_name:
        casts, browser = pychromecast.get_listed_chromecasts(friendly_names=[speaker_name], known_hosts=known_hosts,
                                                             discovery_timeout=10)
    else:
        casts, browser = pychromecast.get_chromecasts(known_hosts=known_hosts)

    # Exactly one match is what we want; anything else stops discovery and gives a clear message
    if len(casts) == 1:
        return casts[0], browser
    elif not casts:
        browser.stop_discovery()
        raise RuntimeError(f"Speaker {speaker_name!r} not found. Run: python -m nestor --list-speakers")
    else:
        browser.stop_discovery()
        names = ", ".join(cast.name for cast in casts)
        raise RuntimeError(f"Several speakers found ({names}). Set speaker_name in config.yaml.")

# One connected speaker: playback, volume, and saving/restoring what it was doing
class Speaker:
    # Connect and wait until the speaker reports its status
    def __init__(self, speaker_name, speaker_host):
        self.cast, self.browser = find_cast(speaker_name, speaker_host)
        self.cast.wait(timeout=15)
        self.name = self.cast.name
        self.host = self.cast.cast_info.host
        self.play_counter = 0
        log.info("Connected to %s at %s", self.name, self.host)

    # Set the speaker volume (0.0 to 1.0)
    def set_volume(self, volume):
        self.cast.set_volume(max(0.0, min(1.0, volume)))

    # Remember the volume and, if the built-in media player was playing something, what and where
    def snapshot(self):
        media_status = self.cast.media_controller.status
        saved = {"volume": self.cast.status.volume_level, "app_id": self.cast.app_id,
                 "app_name": self.cast.app_display_name, "resume": None}
        playing = media_status.player_state in ACTIVE_STATES + (MEDIA_PLAYER_STATE_PAUSED,)

        # Only media in the built-in player can be resumed; Spotify and similar apps can't be restarted from here
        if self.cast.app_id == DEFAULT_MEDIA_RECEIVER and playing and media_status.content_id:
            saved["resume"] = {"url": media_status.content_id, "content_type": media_status.content_type,
                               "position": media_status.adjusted_current_time, "title": media_status.title,
                               "live": media_status.stream_type_is_live,
                               "paused": media_status.player_state == MEDIA_PLAYER_STATE_PAUSED}
        return saved

    # Put the volume back and resume earlier media where possible
    def restore(self, saved):
        self.set_volume(saved["volume"])
        resume = saved["resume"]

        # Restart the earlier media at the position it was interrupted
        if resume:
            position = None if resume["live"] else resume["position"]
            self.cast.media_controller.play_media(resume["url"], resume["content_type"] or "audio/mpeg",
                                                  title=resume["title"], current_time=position,
                                                  autoplay=not resume["paused"],
                                                  stream_type="LIVE" if resume["live"] else "BUFFERED")
        elif saved["app_id"] and saved["app_id"] != DEFAULT_MEDIA_RECEIVER and saved["app_name"] != "Backdrop":
            log.info("%s was playing and can't be resumed automatically", saved["app_name"])

    # Play one audio URL and block until it has finished (or a timeout passes). expected_seconds is for clips the
    # speaker never reports as finished (Google Home Speaker hangs ~30 s after WAV files): done once that long played.
    def play_and_wait(self, url, content_type, expected_seconds=None, max_seconds=180):
        # A unique query string means the status for this play can't be mixed up with an earlier one
        self.play_counter += 1
        unique_url = f"{url}?play={int(time.time())}-{self.play_counter}"
        media = self.cast.media_controller
        media.play_media(unique_url, content_type, stream_type="BUFFERED")
        media.block_until_active(timeout=15)
        start_deadline = time.time() + 15
        end_deadline = time.time() + max_seconds
        playing_since = None

        # Poll the player: wait for this URL to start, then for it to finish
        while time.time() < end_deadline:
            media_status = media.status
            is_this_media = media_status.content_id == unique_url
            player_state = media_status.player_state

            # Note when playback begins, and stop waiting once it is over
            if is_this_media and player_state in ACTIVE_STATES and playing_since is None:
                playing_since = time.time()
            elif is_this_media and player_state == MEDIA_PLAYER_STATE_IDLE and media_status.idle_reason == "ERROR":
                raise RuntimeError(f"Speaker could not play {url}")
            elif is_this_media and player_state == MEDIA_PLAYER_STATE_IDLE and (
                    playing_since or media_status.idle_reason == "FINISHED"):
                return
            elif playing_since and expected_seconds and time.time() - playing_since > expected_seconds + 0.3:
                return
            elif not playing_since and time.time() > start_deadline:
                raise RuntimeError(f"Speaker did not start playing {url}")
            time.sleep(0.1)
        log.warning("Gave up waiting for %s to finish", url)

    # Close the connection to the speaker and stop network discovery
    def disconnect(self):
        self.cast.disconnect(timeout=5)
        self.browser.stop_discovery()
