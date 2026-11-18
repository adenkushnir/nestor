# Runs the Nestor service (python -m nestor), lists the speakers on the network (--list-speakers), makes a code for
# pairing the Datebook phone app (--pair), or shows the microphone's levels for Hey John (--mic-test)
import argparse
import logging
import time
from nestor.config import load_config
from nestor.datebook import PAIRING_MINUTES
from nestor.datebook import new_pairing_code
from nestor.microphone import mic_test
from nestor.service import Service
from nestor.speaker import list_speakers

# Parse the options and either list speakers or run the service until Ctrl+C
def main():
    parser = argparse.ArgumentParser(prog="python -m nestor", description="Run the Nestor speaker service.")
    parser.add_argument("--list-speakers", action="store_true", help="show the Cast speakers on the network and exit")
    parser.add_argument("--pair", action="store_true", help="make a code to pair the Datebook phone app and exit")
    parser.add_argument("--mic-test", action="store_true", help="show the microphone's levels for Hey John and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    # Listing, pairing and the microphone test don't need the service
    if args.list_speakers:
        list_speakers()
        return
    elif args.pair:
        code = new_pairing_code()
        print(f"Pairing code: {code[:3]} {code[3:]}")
        print(f"In Datebook, open Settings > Nestor and type it in within {PAIRING_MINUTES} minutes.")
        return
    elif args.mic_test:
        mic_test(load_config())
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
