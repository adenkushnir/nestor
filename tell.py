# Runs a command, then has the speaker say how it went, e.g. python tell.py python train.py
import argparse
import os
import subprocess
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # Lets it run from any folder
from nestor.client import post_to_nestor
from nestor.config import load_config
from nestor.spoken import spoken_duration
from nestor.spoken import spoken_name
# Words skipped when naming a command, so "npm run build" is called "build"
LAUNCHER_WORDS = {"python", "python3", "py", "node", "npm", "npx", "bash", "sh", "uv", "gradle", "gradlew", "run"}

# Pick a short name to say for the command: the script, not the interpreter ("python train.py" -> "train")
def command_name(command):
    words = list(command)

    # Skip interpreters, "run" and options to reach the script or task name
    while len(words) > 1 and (os.path.splitext(os.path.basename(words[0]))[0].lower() in LAUNCHER_WORDS
                              or words[0].startswith("-")):
        # Inline code (python -c "...") has no name worth saying
        if words[0] == "-c":
            return "your command"
        words.pop(0)
    return os.path.splitext(os.path.basename(words[0]))[0]

# Run the command, then announce whether it finished or failed, and how long it took
def main():
    parser = argparse.ArgumentParser(description="Run a command, then announce when it is done.",
                                     usage="tell.py [--name NAME] command [arguments ...]")
    parser.add_argument("--name", help="what to call the command when announcing it")
    parser.add_argument("command", nargs=argparse.REMAINDER, help="the command to run")
    args = parser.parse_args()

    # There must be something to run
    if not args.command:
        parser.error("give a command to run")
    name = args.name or spoken_name(command_name(args.command), load_config())
    started = time.time()

    # Run it like the terminal would; Ctrl+C means you're here, so nothing is announced
    try:
        exit_code = subprocess.call(args.command, shell=(os.name == "nt"))
    except KeyboardInterrupt:
        sys.exit(130)
    took = spoken_duration(time.time() - started)

    # Say whether it worked
    if exit_code == 0:
        message = f"{name} finished after {took}."
    else:
        message = f"{name} failed after {took}, with exit code {exit_code}."
    message = message[0].upper() + message[1:]

    # Hand the alert to Nestor, which holds it overnight during quiet hours
    try:
        sent = post_to_nestor("/alert", {"text": message}, timeout=10)
    except (ValueError, OSError) as error:
        sent = False
        print(f"tell: could not reach Nestor ({error})", file=sys.stderr)

    # Mention it when the announcement couldn't be made
    if not sent:
        print(f"tell: Nestor isn't running, so this wasn't announced: {message}", file=sys.stderr)
    sys.exit(exit_code)

# Run only when started as a script
if __name__ == "__main__":
    main()
