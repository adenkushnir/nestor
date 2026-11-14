# Runs the Nestor service (python -m nestor), or lists the speakers on the network (--list-speakers)
import argparse
import logging
import time
from nestor.config import load_config
from nestor.service import Service
from nestor.speaker import list_speakers

# Parse the options and either list speakers or run the service until Ctrl+C
def main():
    parser = argparse.ArgumentParser(prog="python -m nestor", description="Run the Nestor speaker service.")
    parser.add_argument("--list-speakers", action="store_true", help="show the Cast speakers on the network and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Listing doesn't need the service
    if args.list_speakers:
        list_speakers()
        return
    service = Service(load_config(), watchers=True)
    print("Nestor is running. Press Ctrl+C to stop.")

    # Keep the main thread alive until Ctrl+C
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        service.stop()

# Run only when started with python -m nestor
if __name__ == "__main__":
    main()
