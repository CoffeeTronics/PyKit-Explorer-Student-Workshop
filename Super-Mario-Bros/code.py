# code.py - CONTROLLER (MVC pattern)
#
# The Controller is the entry point.  It owns ALL hardware objects,
# initialises them, and drives the main game loop.
#
# Responsibilities:
#   - Hardware initialisation (display, IMU, NeoPixels, touch pad, button)
#   - IMU calibration and input normalisation into [-1.0, 1.0]
#   - Jump buffering so fast taps are not missed during draw() or sleep()
#   - Creating MarioModel and MarioView and wiring them together
#   - Main game loop:
#       1. Poll jump button immediately (catches presses during slow frames)
#       2. Read all inputs -> fill InputState
#       3. model.update(input_state) -> list of event strings
#       4. Route each event to the appropriate view method
#       5. view.draw(model) to reposition sprites
#       6. view.update_neopixels(model) for LED feedback
#       7. Periodic GC and debug print
#       8. Game-over hold screen (5 s, then reset and continue)

import sys
sys.path.append("/API")

import time
import board
import digitalio
import microcontroller
import touchio
import neopixel
import gc
import adafruit_icm20x
import displayio
from fourwire import FourWire
from adafruit_st7789 import ST7789
import terminalio
from adafruit_display_text import label as _label

from mario_model import MarioModel, InputState
from mario_view  import MarioView

# ---------------------------------------------------------------------------
# Controller configuration
# ---------------------------------------------------------------------------
TILT_DEADZONE       = 0.8   # minimum g-force tilt to register movement
TILT_MAX            = 6.0   # g-force tilt that gives maximum speed (1.0)
CALIBRATION_SAMPLES = 30    # IMU samples averaged at startup for bias removal
Debug               = True  # print frame stats to the serial console


# ---------------------------------------------------------------------------
# Display setup
# ---------------------------------------------------------------------------
def _setup_display():
    """Initialise the ST7789 LCD and return the display object.

    The backlight is kept off during init to prevent a white flash.
    Display rotation is 90 degrees (landscape), matching the physical
    orientation of the board.
    """
    backlight           = digitalio.DigitalInOut(microcontroller.pin.PA06)
    backlight.direction = digitalio.Direction.OUTPUT
    backlight.value     = False   # off during init

    displayio.release_displays()

    spi         = board.LCD_SPI()
    display_bus = FourWire(spi, command=board.D4, chip_select=board.LCD_CS)
    display     = ST7789(
        display_bus,
        rotation=90,
        width=240, height=135,
        rowstart=40, colstart=53,
    )
    print("Display OK")
    return display


# ---------------------------------------------------------------------------
# IMUController
# ---------------------------------------------------------------------------
class IMUController:
    """Read the ICM20948 IMU and D3 jump button each tick.

    Hardware used (all owned by the Controller, not the Model):
      board.I2C()  -- I2C bus for the IMU
      board.D3     -- jump button (active-LOW, internal pull-up)
      board.CAP1   -- capacitive touch pad for "run"

    Calibration
    -----------
    On startup, CALIBRATION_SAMPLES accelerometer readings are averaged to
    find the static bias on the X axis.  This offset is subtracted from
    every subsequent reading so the board can be held at any angle and
    still give a stable zero point.

    Jump buffering
    --------------
    A button press is held in a 3-frame buffer so quick taps are not
    missed during a slow draw() or sleep() call.  poll_button() should
    be called at the very start of each frame before any other work.
    """

    def __init__(self):
        print("Initialising IMU...")
        i2c = board.I2C()
        try:
            self._icm = adafruit_icm20x.ICM20948(i2c, 0x69)
            print("IMU at 0x69")
        except Exception:
            self._icm = adafruit_icm20x.ICM20948(i2c, 0x68)
            print("IMU at 0x68")

        self._offset_x = 0.0   # bias offset set by calibrate()

        # Jump button on D3 (active LOW with internal pull-up)
        self._btn           = digitalio.DigitalInOut(board.D3)
        self._btn.direction = digitalio.Direction.INPUT
        self._btn.pull      = digitalio.Pull.UP
        self._prev_btn      = True    # True = not pressed (pull-up)
        self._buf_frames    = 0       # frames remaining in jump buffer

        # Capacitive touch for run
        try:
            self._touch     = touchio.TouchIn(board.CAP1)
            self._has_touch = True
            print("Touch pad OK")
        except Exception:
            self._has_touch = False

        # Debounce for run: touchio.TouchIn.value emits brief False glitches
        # while the pad is genuinely held.  Latch True immediately on press;
        # only release after _RUN_RELEASE_FRAMES consecutive False readings.
        self._run_stable    = False   # debounced run state passed to InputState
        self._run_off_count = 0       # consecutive frames of raw False

        # Re-used each tick to avoid allocation
        self._state = InputState()

        self.calibrate()

    def calibrate(self):
        """Average CALIBRATION_SAMPLES IMU readings to find the resting bias."""
        print("Calibrating IMU -- place board on a level surface...")
        time.sleep(1)
        total = 0.0
        for _ in range(CALIBRATION_SAMPLES):
            x, _, _ = self._icm.acceleration
            total  += x
            time.sleep(0.05)
        self._offset_x = total / CALIBRATION_SAMPLES
        print(f"Calibration done. X offset = {self._offset_x:.2f} g")

    def poll_button(self):
        """Quick poll of the jump button only.

        Call this at the very start of every frame (before draw() and
        sleep()) so that fast taps during those calls are buffered and
        not lost.
        """
        current = not self._btn.value   # active-LOW: True when pressed
        if current and not self._prev_btn:
            self._buf_frames = 3        # keep buffered for 3 frames (~100 ms)
        self._prev_btn = current

    def read(self) -> InputState:
        """Read all inputs and return a filled InputState for this tick.

        Also polls the button again (redundant but harmless) to catch
        any press that happened since the last poll_button() call.
        """
        # Tilt -- horizontal X axis of the accelerometer
        ax, _, _ = self._icm.acceleration
        adj       = ax - self._offset_x

        if abs(adj) < TILT_DEADZONE:
            self._state.tilt_value = 0.0
        elif adj > 0:
            # Moving right: normalise to [0.0, 1.0] after removing deadzone
            self._state.tilt_value = min(1.0, (adj - TILT_DEADZONE) / TILT_MAX)
        else:
            # Moving left: normalise to [-1.0, 0.0]
            self._state.tilt_value = max(-1.0, (adj + TILT_DEADZONE) / TILT_MAX)

        # Jump button (poll again + consume buffer)
        current = not self._btn.value
        if current and not self._prev_btn:
            self._buf_frames = 3
        self._prev_btn = current

        if self._buf_frames > 0:
            self._state.jump  = True
            self._buf_frames -= 1
        else:
            self._state.jump  = False

        # Run (capacitive touch) -- debounced to suppress brief False glitches.
        # Latch True as soon as the pad is touched; only clear after
        # _RUN_RELEASE_FRAMES (3) consecutive False readings so that
        # single-frame noise doesn't flash the amber NeoPixel off.
        raw_run = self._touch.value if self._has_touch else False
        if raw_run:
            self._run_stable    = True
            self._run_off_count = 0
        else:
            self._run_off_count += 1
            if self._run_off_count >= 3:
                self._run_stable = False
        self._state.run = self._run_stable

        return self._state


# ---------------------------------------------------------------------------
# Startup LCD helper
# ---------------------------------------------------------------------------
def _show_startup_text(display, lines):
    """Render centred white text on a black screen.

    Used for pre/post-calibration messages before MarioView takes over
    the display.  Each entry in *lines* is drawn on its own row at scale 2
    (12 px wide x 16 px tall per character); keep each line under 20 chars.

    Parameters
    ----------
    display : ST7789 display object
    lines   : list of str
    """
    grp    = displayio.Group()
    bg_bmp = displayio.Bitmap(240, 135, 1)
    bg_pal = displayio.Palette(1)
    bg_pal[0] = 0x000000            # black background
    grp.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))

    # Space rows evenly across the 135-px height
    row_h   = 22                    # pixels between baselines at scale 2
    total_h = len(lines) * row_h
    start_y = (135 - total_h) // 2 + row_h // 2

    for i, text in enumerate(lines):
        lbl = _label.Label(
            terminalio.FONT,
            text=text,
            color=0xFFFFFF,
            scale=2,
            anchor_point=(0.5, 0.5),
            anchored_position=(120, start_y + i * row_h),
        )
        grp.append(lbl)

    display.root_group = grp


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    gc.collect()
    print(f"Free RAM at start: {gc.mem_free()} bytes")

    # -- Hardware initialisation ---------------------------------------------
    display = _setup_display()
    px      = neopixel.NeoPixel(board.NEOPIXEL, 5, brightness=0.15,
                                auto_write=False)
    px.fill(0x000000)
    px.show()

    # -- Pre-calibration LCD message -----------------------------------------
    # Show before IMUController() so the user sees it during the ~2.5 s
    # calibration window (1 s sleep + 30 samples * 50 ms each).
    _show_startup_text(display, [
        "Place Ruler flat.",
        "IMU Calibration",
        "starting...",
    ])

    # -- IMU (calibrates on construction) ------------------------------------
    imu = IMUController()

    # -- Post-calibration LCD message ----------------------------------------
    _show_startup_text(display, [
        "IMU Calibration",
        "Completed",
    ])

    # -- Remaining MVC objects -----------------------------------------------
    # MarioView sets display.root_group, replacing the calibration screen.
    model = MarioModel()
    view  = MarioView(display, px)

    print("\n" + "=" * 50)
    print("SUPER MARIO BROS - IMU EDITION")
    print("Tilt board to move | D3 = jump | CAP1 = run")
    print("=" * 50 + "\n")

    frame            = 0
    gameover_holding = False   # True while showing the 5-second hold screen

    # -- Main game loop ------------------------------------------------------
    while True:
        # Poll jump button at the very top of the frame to catch quick taps
        # that may have occurred during the previous draw() or sleep().
        imu.poll_button()

        # Read all hardware inputs into a decoupled InputState
        input_state = imu.read()

        # Advance the model by one tick; collect any events that fired
        events = model.update(input_state)

        # Route events to the appropriate view methods
        for event in events:
            if event == "jumped":
                view.play_sfx("jump")

            elif event == "coin":
                view.play_sfx("coin")

            elif event == "stomp":
                pass   # add view.play_sfx("stomp") when smb_stomp.wav is ready

            elif event == "enemy_hit":
                pass   # add view.play_sfx("death") when smb_death.wav is ready

            elif event == "gameover":
                view.play_sfx("gameover")
                view.show_game_over()
                view.flash_neopixels_gameover()
                gameover_holding = False   # start the hold-screen countdown

            elif event == "level_complete":
                view.play_sfx("world_clear")
                view.show_victory(model.score, model.coins)

            elif event == "level_reset":
                # Model already called reset(); sync the view
                view.hide_overlays()

        # Render the frame
        view.draw(model)
        view.update_neopixels(model, model.level_complete)

        frame += 1

        # Periodic GC every ~3 seconds at 30 FPS
        if frame % 90 == 0:
            gc.collect()
            if Debug or frame % 180 == 0:
                print(f"Score: {model.score} | Coins: {model.coins} | "
                      f"Lives: {model.lives} | RAM: {gc.mem_free()}")

        # Game-over hold screen -- display for 5 seconds, then auto-restart
        if model.game_over and not gameover_holding:
            gameover_holding = True
            print(f"\nGAME OVER!  Final score: {model.score}")

            for i in range(150):   # 150 frames * 33 ms = ~5 seconds
                time.sleep(0.033)
                if i % 30 == 0:    # print status every second
                    if view.is_audio_playing():
                        print(f"  gameover audio playing... ({i // 30 + 1}s)")
                    else:
                        print(f"  holding screen... ({i // 30 + 1}s)")

            print("Restarting level...\n")
            view.stop_audio()
            model.reset()         # full game reset in the Model
            view.hide_overlays()  # clear overlays and show HUD in the View
            gameover_holding = False

        time.sleep(0.033)   # ~30 FPS


if __name__ == "__main__":
    main()
