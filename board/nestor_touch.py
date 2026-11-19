# Touch for the Raspberry Pi 7-inch screen on the Tinker Board: reads its FT5406 touch chip over I2C a few dozen times
# a second (the screen has no "touch happened" wire, so Linux's own driver can't be used) and passes the touches to
# the system as a touchscreen
import argparse
import logging
import time
import evdev
import smbus
from evdev import ecodes
FIRST_REGISTER = 0x02  # The touch count, followed by 6 bytes for each touch point
MAX_POINTS = 5  # Points read each time (31 bytes, inside the 32-byte limit of one I2C block read)
RELEASED = 1  # A point's event bits when the finger has just lifted
log = logging.getLogger("nestor-touch")

# The touch points in one reading of the chip, as {touch id: (x, y)} in screen pixels; None if the reading is garbage
# (the chip answers all 0xFF while it starts up)
def read_points(data, width, height, flip_x, flip_y):
    count = data[0] & 0x0F

    # More points than the chip supports means a bad reading
    if count > 10:
        return None
    points = {}

    # Each reported point (6 bytes: event and x high, x low, id and y high, y low, weight, area)
    for index in range(min(count, MAX_POINTS)):
        part = data[1 + 6 * index:7 + 6 * index]
        event = part[0] >> 6
        x = ((part[0] & 0x0F) << 8) | part[1]
        y = ((part[2] & 0x0F) << 8) | part[3]
        touch_id = part[2] >> 4

        # A finger that has just lifted isn't a touch any more
        if event == RELEASED:
            continue
        x = width - 1 - x if flip_x else x
        y = height - 1 - y if flip_y else y
        points[touch_id] = (max(0, min(width - 1, x)), max(0, min(height - 1, y)))
    return points

# A virtual touchscreen the system treats like a real one
def make_device(width, height):
    capabilities = {
        ecodes.EV_KEY: [ecodes.BTN_TOUCH],
        ecodes.EV_ABS: [
            (ecodes.ABS_X, evdev.AbsInfo(0, 0, width - 1, 0, 0, 0)),
            (ecodes.ABS_Y, evdev.AbsInfo(0, 0, height - 1, 0, 0, 0)),
            (ecodes.ABS_MT_SLOT, evdev.AbsInfo(0, 0, 15, 0, 0, 0)),
            (ecodes.ABS_MT_TRACKING_ID, evdev.AbsInfo(0, 0, 65535, 0, 0, 0)),
            (ecodes.ABS_MT_POSITION_X, evdev.AbsInfo(0, 0, width - 1, 0, 0, 0)),
            (ecodes.ABS_MT_POSITION_Y, evdev.AbsInfo(0, 0, height - 1, 0, 0, 0)),
        ],
    }
    return evdev.UInput(capabilities, name="Raspberry Pi 7-inch touchscreen", input_props=[ecodes.INPUT_PROP_DIRECT])

# Send the change from the last points to these ones: each finger is a slot (its touch id) with a tracking number
def send_points(device, points, previous, tracking, next_tracking):
    # Fingers that lifted end their tracking
    for touch_id in previous:
        # Gone this time
        if touch_id not in points:
            device.write(ecodes.EV_ABS, ecodes.ABS_MT_SLOT, touch_id)
            device.write(ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, -1)
            tracking.pop(touch_id, None)

    # Fingers down: new ones get a tracking number, and each says where it is
    for touch_id, (x, y) in points.items():
        device.write(ecodes.EV_ABS, ecodes.ABS_MT_SLOT, touch_id)

        # A finger that just came down
        if touch_id not in tracking:
            tracking[touch_id] = next_tracking
            next_tracking = (next_tracking + 1) % 65536
            device.write(ecodes.EV_ABS, ecodes.ABS_MT_TRACKING_ID, tracking[touch_id])
        device.write(ecodes.EV_ABS, ecodes.ABS_MT_POSITION_X, x)
        device.write(ecodes.EV_ABS, ecodes.ABS_MT_POSITION_Y, y)

    # The single-touch view: the first finger, and whether anything touches at all
    if points:
        x, y = points[min(points)]
        device.write(ecodes.EV_ABS, ecodes.ABS_X, x)
        device.write(ecodes.EV_ABS, ecodes.ABS_Y, y)
    device.write(ecodes.EV_KEY, ecodes.BTN_TOUCH, 1 if points else 0)
    device.syn()
    return next_tracking

# Read the chip over and over, passing touches on; read errors are logged once and retried
def main():
    parser = argparse.ArgumentParser(description="Touch for the Raspberry Pi 7-inch screen")
    parser.add_argument("--bus", type=int, default=3)
    parser.add_argument("--address", type=lambda text: int(text, 0), default=0x38)
    parser.add_argument("--width", type=int, default=800)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--no-flip", action="store_true",
                        help="don't mirror x and y (this screen reports them mirrored)")
    parser.add_argument("--rate", type=float, default=60, help="readings a second")
    options = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    bus = smbus.SMBus(options.bus)
    device = make_device(options.width, options.height)
    flip = not options.no_flip
    previous, tracking, next_tracking, failing = {}, {}, 0, False
    log.info("Reading touches from I2C bus %d, address 0x%02x", options.bus, options.address)

    # For the life of the service
    while True:
        # A failed read waits a moment; the chip may be restarting with the screen
        try:
            data = bus.read_i2c_block_data(options.address, FIRST_REGISTER, 1 + 6 * MAX_POINTS)
        except OSError as error:
            # Say it once, not every time
            if not failing:
                log.warning("Can't read the touch chip: %s", error)
                failing = True
            time.sleep(0.5)
            continue

        # Reading again after failures
        if failing:
            log.info("Reading the touch chip again")
            failing = False
        points = read_points(data, options.width, options.height, flip, flip)

        # Only real readings that changed are sent
        if points is not None and points != previous:
            next_tracking = send_points(device, points, previous, tracking, next_tracking)
            previous = points
        time.sleep(1 / options.rate)

# Run as a program
if __name__ == "__main__":
    main()
