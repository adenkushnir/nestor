# Announces Nestor on the home Wi-Fi (mDNS, service type _nestor._tcp), so the Datebook phone app finds it with no
# address to type, and keeps finding it after Nestor moves from the PC to the Tinker Board
import logging
import socket
from zeroconf import ServiceInfo
from zeroconf import Zeroconf
SERVICE_TYPE = "_nestor._tcp.local."
SERVICE_NAME = f"Nestor.{SERVICE_TYPE}"
log = logging.getLogger(__name__)

# Keeps Nestor's announcement up while the service runs
class Advertiser:
    # Start announcing Nestor's web server at this LAN address and port
    def __init__(self, ip, port):
        self.zeroconf = Zeroconf(interfaces=[ip])
        self.info = ServiceInfo(SERVICE_TYPE, SERVICE_NAME, addresses=[socket.inet_aton(ip)], port=port,
                                properties={"version": "1"}, server=f"nestor-{socket.gethostname().lower()}.local.")
        self.zeroconf.register_service(self.info, allow_name_change=True)
        log.info("Announcing Nestor on the network as %s", self.info.name)

    # Take the announcement down and close the network connection
    def stop(self):
        self.zeroconf.unregister_service(self.info)
        self.zeroconf.close()
