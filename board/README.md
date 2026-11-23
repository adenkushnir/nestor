# The Tinker Board and its 7-inch screen

Nestor's wall display runs on an **ASUS Tinker Board S** (Rockchip RK3288, 32-bit, 2 GB) in a SmartiPi Touch case
with the **official Raspberry Pi 7-inch touchscreen** (800 × 480, DSI ribbon cable) and a USB microphone. This folder
has what it takes to make that screen work on [Armbian](https://www.armbian.com/tinkerboard/) (Debian 13), and to run
Nestor itself on the board.

| File | What it is |
|---|---|
| `kernel-screen.config` | Kernel settings Armbian leaves out: the DSI output and the screen's drivers |
| `rockchip-dsi-exact-non-burst-rate.patch` | A kernel fix: runs the DSI link at exactly the speed the screen's bridge chip needs |
| `tinker-rpi-7inch.dts` | A device tree overlay: switches on I2C bus 3 and the DSI output, and adds the screen with its timings |
| `nestor_touch.py` | Reads the touch chip and passes touches to the system as a touchscreen |
| `nestor-touch.service` | Runs `nestor_touch.py` at start-up |
| `copy-to-emmc.sh` | Copies the finished system from the microSD card to the board's built-in storage (eMMC) |
| `screen-ruler.html` | A test picture for checking the screen's picture is lined up to the pixel |
| `install-nestor.sh` | Installs Nestor on the board: Debian's packages, the code from GitHub, Python and John's Vosk model |
| `requirements-board.txt` | Nestor's Python packages on the board (on top of Debian's) |
| `nestor.service` | Runs Nestor from power-on as your account |
| `nestor-screen.service` | Shows Nestor's screen page full-screen on the 7-inch screen (a `cage` kiosk with Chromium) |

## Why it needs all this

- **Armbian's kernel has no DSI output or screen drivers** for this board, and the DSI output is part of the
  built-in graphics driver, so it can't be added as a module. The kernel has to be built with
  `kernel-screen.config`.
- **The screen isn't described** in Armbian's device tree. On ASUS's own Tinker OS it is: the screen's control chip
  (an ATtiny) is at `0x45` and the FT5406 touch chip at `0x38`, both on I2C bus 3 (`i2c@ff150000`), and the picture
  goes out of `dsi@ff960000`. `tinker-rpi-7inch.dts` says the same for Armbian.
- **The picture was shifted sideways, with wrong colours.** The screen's TC358762 bridge chip turns the DSI signal
  back into pixels using the link's speed, so the link has to run at exactly the pixel clock × 24. The kernel's
  Rockchip DSI driver adds 25% on top, which the patch removes for this kind of link (non-burst video). The overlay
  then uses a 27.0 MHz pixel clock (one the board makes exactly, giving 648 Mbit/s), 24-bit colour (`rgb24`), and
  porches lined up to the pixel: 50 / 20 / 46 across, 7 / 2 / 21 down.
- **Touch:** Linux's FT5406 driver needs an interrupt wire, which this screen doesn't have, so `nestor_touch.py`
  reads the chip about 60 times a second instead. The screen reports positions mirrored both ways;
  the program flips them back.

## Setting up a board

1. **The card:** write Armbian's Debian 13 Minimal image for Tinker Board to a microSD card (e.g. with balenaEtcher).
   On the Tinker Board S, put the jumper between the micro-USB and HDMI ports on **Maskrom** (the cap on the two
   pins farther from the edge) so it starts from the card. Do the first-time setup with a TV and keyboard on HDMI.
2. **Build the kernel** on a Linux PC (WSL on Windows works) with
   [armbian/build](https://github.com/armbian/build) on the branch matching the board's Armbian version (e.g.
   `v26.08`):

   ```bash
   git clone --depth 1 -b v26.08 https://github.com/armbian/build && cd build
   mkdir -p userpatches/kernel/archive/rockchip-6.18
   cp config/kernel/linux-rockchip-current.config userpatches/
   cat /path/to/kernel-screen.config >> userpatches/linux-rockchip-current.config
   cp /path/to/rockchip-dsi-exact-non-burst-rate.patch \
      userpatches/kernel/archive/rockchip-6.18/zz-nestor-rockchip-dsi-exact-non-burst-rate.patch
   ./compile.sh kernel BOARD=tinkerboard BRANCH=current KERNEL_CONFIGURE=no
   ```

   The packages land in `output/debs/` (about 15 minutes on a laptop). The patch folder is named after the kernel
   version (6.18 here); check the build log says the patch was applied.
3. **On the board** (as root), install the kernel and keep Armbian's updates from replacing it, add the overlay,
   and restart:

   ```bash
   dpkg -i linux-image-current-rockchip_*.deb linux-dtb-current-rockchip_*.deb
   apt-mark hold linux-image-current-rockchip linux-dtb-current-rockchip
   armbian-add-overlay tinker-rpi-7inch.dts
   poweroff
   ```

   Then unplug the power for 10 seconds: the screen keeps its own power through a restart, and needs a fresh start
   the first time.
4. **Touch:**

   ```bash
   apt install python3-smbus python3-evdev
   mkdir -p /usr/local/lib/nestor && cp nestor_touch.py /usr/local/lib/nestor/
   cp nestor-touch.service /etc/systemd/system/ && systemctl enable --now nestor-touch
   ```

5. **Move to the built-in storage (eMMC)** so the card is free. The Maskrom jumper also hides the eMMC, so with the
   board running from the card, take the jumper cap off, make the board look for the eMMC again, and copy (this
   wipes the eMMC):

   ```bash
   echo ff0f0000.mmc > /sys/bus/platform/drivers/dwmmc_rockchip/unbind
   echo ff0f0000.mmc > /sys/bus/platform/drivers/dwmmc_rockchip/bind
   lsblk    # the eMMC shows up as mmcblk2 (14.7 GB)
   bash copy-to-emmc.sh
   poweroff
   ```

   Don't restart in between: without the cap the board starts from whatever is on the eMMC. When it ends with
   `EMMC-COPY-OK`, unplug the power, take the card out, leave the cap off, and plug back in. The card stays as a
   backup: to start from it again, put it back and the cap on Maskrom.

## Running Nestor on the board

Nestor runs on the board as your own account, from `~/nestor` (a clone of this repo). Everything works as on a PC,
except that **John hears you with [Vosk](https://alphacephei.com/vosk/)** instead of Whisper: Whisper takes 17-19
seconds per request on this processor and heats it to its 90 °C cut-off within a minute, while Vosk keeps up as you
speak on one core (about 60 °C). Vosk writes no punctuation, so John also wakes on a short phrase ending in "John"
("turn the wall blue john"), not only on "Hey John". The microphone is read with Linux's `arecord`, as pvrecorder
doesn't support the board's processor.

Vosk's small model mishears a lot of questions ("what time is up"), so **John can hear what you ask in the cloud**.
With `speech_to_text: "openai"` and `OPENAI_API_KEY=sk-...` in `.env`, Vosk on the board still listens for "Hey
John", and only what's said after it goes to OpenAI's `gpt-transcribe` (about $0.0045 a minute, so cents a month).
If OpenAI can't be reached within 8 seconds, Vosk hears it instead.

1. **Install** (as root on the board; replace `aden` with your account):

   ```bash
   curl -sSLO https://raw.githubusercontent.com/adenkushnir/nestor/main/board/install-nestor.sh
   bash install-nestor.sh aden
   timedatectl set-timezone America/New_York    # your time zone: Armbian starts on UTC
   ```

   The time zone matters: on UTC, reminders and alarms come hours early or late.

2. **Copy your private files** from the PC (in Git Bash, in the project folder). They never go through GitHub:

   ```bash
   tar -cf - .env config.yaml reminders.yaml data | ssh aden@<board address> 'tar -xf - -C ~/nestor && chmod 600 ~/nestor/.env'
   ```

3. **The board's settings** in `~/nestor/config.yaml`:

   ```yaml
   speech_to_text: "vosk" # or "openai" with OPENAI_API_KEY in .env (see above)
   microphone: "USB"      # part of the microphone's name (arecord -l lists them)
   trial: false           # true while the PC's Nestor still runs (see below)
   ```

4. **The microphone's level:** many USB microphones start at 0% or with an automatic gain that boosts background
   noise. Card 2 here; `arecord -l` shows yours:

   ```bash
   amixer -c 2 sset Mic 8 cap
   amixer -c 2 sset "Auto Gain Control" off
   alsactl store
   ```

5. **Start it from power-on**, with the screen page:

   ```bash
   cp ~aden/nestor/board/nestor.service ~aden/nestor/board/nestor-screen.service /etc/systemd/system/
   systemctl enable --now nestor nestor-screen
   journalctl -u nestor -f     # Nestor's log
   ```

6. **On the PC**, point the Claude connector, the Claude Code hook and the scripts at the board with
   `nestor_url: "http://<board address>:8765"` in its `config.yaml` (see "Claude Code and Claude Desktop" in the main
   README for pairing the connector), and stop the PC's own Nestor.

**Trial mode** (`trial: true`) is for trying the board while the PC's Nestor keeps running: the board leaves out
reminders, heads-ups, timers ringing, GitHub alerts, Spotify and the Datebook link (the PC does those, so nothing is
said twice), while John and direct commands work. Set `john: false` on the PC meanwhile, so only one John listens.

**GitHub alerts** use the GitHub CLI's login: `apt install gh`, then `gh auth login` as your account on the board.

**Updating:** `cd ~/nestor && git pull && sudo systemctl restart nestor` (the screen page reloads by itself).

## Things to know

- **Don't scan I2C bus 3** (e.g. `i2cdetect -y 3`): the screen's control chip jams, and then the screen only comes
  back after unplugging the power (a restart isn't enough, as the screen is powered separately). Reading the touch
  chip directly (`i2cget -y 3 0x38 0xa3` gives `0x54`) is fine.
- **Unplug HDMI** when using the 7-inch screen: with a TV also plugged in, the console takes the TV's size and the
  7-inch screen shows only a zoomed-in corner of it.
- **Lining up the picture:** `screen-ruler.html` puts red bars 2, 4, 6 … pixels wide at the left edge. The first bar
  you can see says how many pixels are hidden; add that to `hback-porch` and take it off `hfront-porch` in the
  overlay (the line length must stay the same).
- **Smoothness** (Chromium 150 in the `cage` kiosk): glass blur over a moving full-screen background runs at the
  screen's full ~58 frames a second.
- Kernel updates are held. To update, rebuild the kernel on the new Armbian branch the same way and install it.
- **Heat:** with only its heatsink (no fan), the board reaches its 90 °C cut-off within a minute or two of all four
  cores working flat out, and switches itself off (screen and lights go dark). Nestor with Vosk and the screen page
  stays around 58 °C.
