#!/bin/bash
# Set up Nestor on the Tinker Board (Armbian, Debian 13): Debian's ready-built packages, the code from GitHub, a Python
# environment and John's Vosk model, all owned by the given account. Run as root: bash install-nestor.sh aden
set -e
account=${1:-aden}
home=$(getent passwd "$account" | cut -d: -f6)
nestor=$home/nestor
vosk_model=vosk-model-small-en-us-0.15
echo "== Debian packages"
DEBIAN_FRONTEND=noninteractive apt-get install -y -q git curl unzip patchelf alsa-utils python3-venv python3-pip \
    python3-numpy python3-onnxruntime python3-sklearn python3-scipy python3-tqdm python3-requests python3-yaml \
    python3-flask python3-zeroconf python3-aiohttp python3-pydantic python3-httpx python3-cffi python3-protobuf > /dev/null
usermod -aG audio "$account"
echo "== code"

# Clone the first time; later updates are a git pull
if [ ! -d "$nestor" ]; then
    sudo -u "$account" git clone -q https://github.com/adenkushnir/nestor "$nestor"
fi
echo "== Python environment"
sudo -u "$account" python3 -m venv --system-site-packages "$nestor/.venv"
sudo -u "$account" "$nestor/.venv/bin/pip" install -q -r "$nestor/board/requirements-board.txt"
sudo -u "$account" "$nestor/.venv/bin/pip" install -q --no-deps "openwakeword>=0.6"
# Vosk's library asks for an executable stack, which Debian 13 refuses; it doesn't need one
patchelf --clear-execstack "$nestor"/.venv/lib/python3*/site-packages/vosk/libvosk.so
echo "== Vosk model"

# Download John's speech-to-text model once (its server sometimes cuts off, so keep resuming)
if [ ! -d "$nestor/$vosk_model" ]; then
    cd "$nestor"

    # Up to 20 tries, resuming where the last one stopped
    for attempt in $(seq 1 20); do
        # Done once the archive is whole
        if sudo -u "$account" curl -sSL -C - -O "https://alphacephei.com/vosk/models/$vosk_model.zip" &&
                unzip -tq "$vosk_model.zip" > /dev/null 2>&1; then
            break
        fi
        sleep 3
    done
    sudo -u "$account" unzip -q "$vosk_model.zip" && rm "$vosk_model.zip"
fi
echo "INSTALL-NESTOR-OK"
