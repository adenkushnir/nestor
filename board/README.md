# The Tinker Board and its 7-inch screen

Nestor's wall display runs on an **ASUS Tinker Board S** (Rockchip RK3288, 32-bit, 2 GB) in a SmartiPi Touch case
with the **official Raspberry Pi 7-inch touchscreen** (800 × 480, DSI ribbon cable). This folder has what it takes
to make that screen work on [Armbian](https://www.armbian.com/tinkerboard/) (Debian 13).

| File | What it is |
|---|---|
| `kernel-screen.config` | Kernel settings Armbian leaves out: the DSI output and the screen's drivers |
| `tinker-rpi-7inch.dts` | A device tree overlay: switches on I2C bus 3 and the DSI output, and adds the screen |
| `nestor_touch.py` | Reads the touch chip and passes touches to the system as a touchscreen |
| `nestor-touch.service` | Runs `nestor_touch.py` at start-up |

## Why it needs all this

- **Armbian's kernel has no DSI output or screen drivers** for this board, and the DSI output is part of the
  built-in graphics driver, so it can't be added as a module. The kernel has to be built with
  `kernel-screen.config`.
- **The screen isn't described** in Armbian's device tree. On ASUS's own Tinker OS it is: the screen's control chip
  (an ATtiny) is at `0x45` and the FT5406 touch chip at `0x38`, both on I2C bus 3 (`i2c@ff150000`), and the picture
  goes out of `dsi@ff960000`. `tinker-rpi-7inch.dts` says the same for Armbian.
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
   mkdir -p userpatches
   cp config/kernel/linux-rockchip-current.config userpatches/
   cat /path/to/kernel-screen.config >> userpatches/linux-rockchip-current.config
   ./compile.sh kernel BOARD=tinkerboard BRANCH=current KERNEL_CONFIGURE=no
   ```

   The packages land in `output/debs/` (about 15 minutes on a laptop).
3. **On the board** (as root), install the kernel and keep Armbian's updates from replacing it, add the overlay,
   and restart:

   ```bash
   dpkg -i linux-image-current-rockchip_*.deb linux-dtb-current-rockchip_*.deb
   apt-mark hold linux-image-current-rockchip linux-dtb-current-rockchip
   armbian-add-overlay tinker-rpi-7inch.dts
   reboot
   ```

4. **Touch:**

   ```bash
   apt install python3-smbus python3-evdev
   mkdir -p /usr/local/lib/nestor && cp nestor_touch.py /usr/local/lib/nestor/
   cp nestor-touch.service /etc/systemd/system/ && systemctl enable --now nestor-touch
   ```

## Things to know

- **Don't scan I2C bus 3** (e.g. `i2cdetect -y 3`): the screen's control chip jams, and then the screen only comes
  back after unplugging the power (a restart isn't enough, as the screen is powered separately). Reading the touch
  chip directly (`i2cget -y 3 0x38 0xa3` gives `0x54`) is fine.
- With HDMI also plugged in, the console shows on both screens.
- Kernel updates are held. To update, rebuild the kernel on the new Armbian branch the same way and install it.
