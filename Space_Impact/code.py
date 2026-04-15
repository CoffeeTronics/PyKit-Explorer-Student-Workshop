# code.py - CONTROLLER (MVC pattern)
#
# The Controller is the entry point.  It owns ALL hardware objects,
# initialises them, and drives the main game loop.
#
# Responsibilities:
#   - Hardware initialisation (display, IMU, NeoPixels, touch pad, button)
#   - IMU calibration (X + Y axes) and input normalisation into [-1.0, 1.0]
#   - Fire-button buffering so fast taps are not missed during draw()/sleep()
#   - Creating SpaceModel and SpaceView and wiring them together
#   - Main game loop:
#       1. Poll fire button immediately (catches presses during slow frames)
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

from space_model import SpaceModel, InputState
from space_view  import SpaceView

# ---------------------------------------------------------------------------
# Controller configuration
# ---------------------------------------------------------------------------
TILT_DEADZONE       = 0.4   # minimum g-force tilt to register movement
TILT_MAX            = 3.0   # g-force tilt that gives maximum speed (1.0)
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
    """Read the ICM20948 IMU, D3 fire button, and CAP1 special button.

    Hardware used (all owned by the Controller):
      board.I2C()  -- I2C bus for the IMU
      board.D3     -- fire button (active-LOW, internal pull-up)
      board.CAP1   -- capacitive touch pad for special weapon

    Calibration
    -----------
    On startup, CALIBRATION_SAMPLES accelerometer readings are averaged
    on BOTH X and Y axes to find the static bias.  This offset is
    subtracted from every subsequent reading so the board can be held
    at any angle and still give a stable zero point.

    Fire-button buffering
    ---------------------
    A button press is held in a 3-frame buffer so quick taps are not
    missed during a slow draw() or sleep() call.
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

        self._offset_x = 0.0
        self._offset_y = 0.0

        # Fire button on D3 (active LOW with internal pull-up)
        self._btn           = digitalio.DigitalInOut(board.D3)
        self._btn.direction = digitalio.Direction.INPUT
        self._btn.pull      = digitalio.Pull.UP
        self._prev_btn      = True    # True = not pressed (pull-up)
        self._btn_held      = False   # True while physically held down
        self._buf_frames    = 0       # frames remaining in fire buffer

        # Capacitive touch for special weapon
        try:
            self._touch     = touchio.TouchIn(board.CAP1)
            self._has_touch = True
            print("Touch pad OK")
        except Exception:
            self._has_touch = False

        # Touch debounce and edge detection for special weapon
        self._touch_stable    = False
        self._touch_off_count = 0
        self._prev_touch      = False   # for edge detection

        # Re-used each tick
        self._state = InputState()

        self.calibrate()

    def calibrate(self):
        """Average CALIBRATION_SAMPLES IMU readings to find resting bias
        on both X and Y axes."""
        print("Calibrating IMU -- place board on a level surface...")
        time.sleep(1)
        total_x = 0.0
        total_y = 0.0
        for _ in range(CALIBRATION_SAMPLES):
            x, y, _ = self._icm.acceleration
            total_x += x
            total_y += y
            time.sleep(0.05)
        self._offset_x = total_x / CALIBRATION_SAMPLES
        self._offset_y = total_y / CALIBRATION_SAMPLES
        print(f"Calibration done.  X={self._offset_x:.2f}  Y={self._offset_y:.2f}")

    def poll_button(self):
        """Quick poll of the fire button only.

        Call at the very start of every frame so fast taps during
        draw() and sleep() are buffered.
        """
        current = not self._btn.value   # active-LOW
        if current and not self._prev_btn:
            self._buf_frames = 3
        self._btn_held = current
        self._prev_btn = current

    def read(self):
        """Read all inputs and return a filled InputState for this tick."""
        # --- Tilt (both axes) ---
        ax, ay, _ = self._icm.acceleration

        # X axis -> horizontal ship movement (left/right)
        adj_x = ax - self._offset_x
        if abs(adj_x) < TILT_DEADZONE:
            self._state.tilt_x = 0.0
        elif adj_x > 0:
            self._state.tilt_x = min(1.0, (adj_x - TILT_DEADZONE) / TILT_MAX)
        else:
            self._state.tilt_x = max(-1.0, (adj_x + TILT_DEADZONE) / TILT_MAX)

        # Y axis -> vertical ship movement (up/down)
        # Negate so that tilting the board "up" (away from you) moves ship up
        adj_y = -(ay - self._offset_y)
        if abs(adj_y) < TILT_DEADZONE:
            self._state.tilt_y = 0.0
        elif adj_y > 0:
            self._state.tilt_y = min(1.0, (adj_y - TILT_DEADZONE) / TILT_MAX)
        else:
            self._state.tilt_y = max(-1.0, (adj_y + TILT_DEADZONE) / TILT_MAX)

        # --- Fire button (D3) -- held = continuous fire + buffer for taps ---
        current = not self._btn.value
        if current and not self._prev_btn:
            self._buf_frames = 3
        self._btn_held = current
        self._prev_btn = current

        # Fire is true while button is physically held OR buffer is active
        if self._btn_held or self._buf_frames > 0:
            self._state.fire = True
            if self._buf_frames > 0:
                self._buf_frames -= 1
        else:
            self._state.fire = False

        # --- Special weapon (CAP1 touch) -- edge-triggered ----------------
        raw_touch = self._touch.value if self._has_touch else False
        if raw_touch:
            self._touch_stable    = True
            self._touch_off_count = 0
        else:
            self._touch_off_count += 1
            if self._touch_off_count >= 3:
                self._touch_stable = False

        # Edge detection: fire special only on rising edge
        if self._touch_stable and not self._prev_touch:
            self._state.special = True
        else:
            self._state.special = False
        self._prev_touch = self._touch_stable

        return self._state


# ---------------------------------------------------------------------------
# Startup LCD helper
# ---------------------------------------------------------------------------
def _show_startup_text(display, lines):
    """Render centred white text on a black screen.

    Used for calibration messages before SpaceView takes over the display.
    """
    grp    = displayio.Group()
    bg_bmp = displayio.Bitmap(240, 135, 1)
    bg_pal = displayio.Palette(1)
    bg_pal[0] = 0x000000
    grp.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))

    row_h   = 22
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
# Game states
# ---------------------------------------------------------------------------
STATE_MENU     = 0   # title screen, waiting for button press
STATE_PLAYING  = 1   # active gameplay
STATE_GAMEOVER = 2   # game-over screen, waiting for button press
STATE_VICTORY  = 3   # all-clear screen, waiting for button press


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def main():
    gc.collect()
    print(f"Free RAM at start: {gc.mem_free()} bytes")

    # -- Hardware initialisation -------------------------------------------
    display = _setup_display()
    px      = neopixel.NeoPixel(board.NEOPIXEL, 5, brightness=0.15,
                                auto_write=False)
    px.fill(0x000000)
    px.show()

    # -- Pre-calibration LCD message ---------------------------------------
    _show_startup_text(display, [
        "Place Ruler flat.",
        "IMU Calibration",
        "starting...",
    ])

    # -- IMU (calibrates on construction) ----------------------------------
    imu = IMUController()

    # -- Post-calibration LCD message --------------------------------------
    _show_startup_text(display, [
        "IMU Calibration",
        "Completed",
    ])

    # -- Remaining MVC objects ---------------------------------------------
    model = SpaceModel()
    view  = SpaceView(display, px)

    print("\n" + "=" * 50)
    print("SPACE IMPACT - PyKit Explorer Edition")
    print("Tilt = move ship | D3 = fire | CAP1 = special")
    print("=" * 50 + "\n")

    frame = 0
    state = STATE_MENU
    gameover_time = 0   # time.monotonic() when game-over started

    # Show the start menu immediately
    view.show_start_menu()
    px.fill(0x000000)
    px.show()
    print("Showing start menu -- press D3 button to start")

    # -- Main game loop ----------------------------------------------------
    while True:
        imu.poll_button()
        input_state = imu.read()

        # ==================================================================
        # STATE: Start menu
        # ==================================================================
        if state == STATE_MENU:
            view.blink_start_prompt()
            # Wait for fire button press to start the game
            if input_state.fire:
                print("Starting game!")
                model.reset()
                view.hide_start_menu()
                view.hide_overlays()
                state = STATE_PLAYING
                frame = 0
                # Small delay so the button press isn't consumed as a shot
                time.sleep(0.2)
                continue

            time.sleep(0.033)
            continue

        # ==================================================================
        # STATE: Game over -- show screen for 2 seconds, then go to menu
        # ==================================================================
        if state == STATE_GAMEOVER:
            if time.monotonic() - gameover_time >= 2.0:
                print("Returning to start menu...\n")
                view.stop_audio()
                view.show_start_menu()
                px.fill(0x000000)
                px.show()
                state = STATE_MENU
                time.sleep(0.2)
                continue

            time.sleep(0.033)
            continue

        # ==================================================================
        # STATE: Victory (all clear) -- wait for button to return to menu
        # ==================================================================
        if state == STATE_VICTORY:
            if input_state.fire:
                print("Returning to start menu...\n")
                view.stop_audio()
                view.show_start_menu()
                px.fill(0x000000)
                px.show()
                state = STATE_MENU
                time.sleep(0.2)
                continue

            time.sleep(0.033)
            continue

        # ==================================================================
        # STATE: Playing
        # ==================================================================
        # Advance the model by one tick
        events = model.update(input_state)

        # Route events to the view
        for event in events:
            if event == "fired":
                view.play_sfx("shoot")

            elif event == "special_fired":
                view.play_sfx("shoot")

            elif event == "enemy_destroyed":
                view.play_sfx("explosion")

            elif event == "boss_hit":
                view.play_sfx("hit")

            elif event == "boss_destroyed":
                view.play_sfx("boss_explode")

            elif event == "player_hit":
                view.play_sfx("hit")

            elif event == "shield_hit":
                view.play_sfx("hit")

            elif event == "powerup_collected":
                view.play_sfx("powerup")

            elif event == "level_complete":
                view.play_sfx("level_clear")
                view.show_victory(model.score, model.level)

            elif event == "level_reset":
                view.hide_overlays()

            elif event == "all_clear":
                view.play_sfx("level_clear")
                view.show_all_clear(model.score)
                state = STATE_VICTORY
                print(f"ALL CLEAR!  Final score: {model.score}")

            elif event == "gameover":
                view.play_sfx("gameover")
                view.show_game_over()
                view.flash_neopixels_gameover()
                state = STATE_GAMEOVER
                gameover_time = time.monotonic()
                print(f"\nGAME OVER!  Final score: {model.score}")

        # Render the frame
        view.draw(model)
        if state == STATE_PLAYING:
            view.update_neopixels(model)

        frame += 1

        # Periodic GC every ~3 seconds at 30 FPS
        if frame % 90 == 0:
            gc.collect()
            if Debug or frame % 180 == 0:
                print(f"LV:{model.level} Score:{model.score} "
                      f"Lives:{model.lives} RAM:{gc.mem_free()}")

        time.sleep(0.033)   # ~30 FPS


if __name__ == "__main__":
    main()
