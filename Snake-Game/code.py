# code.py - CONTROLLER (MVC pattern)
#
# The Controller is the "glue" that connects the Model and View.
# It is the entry point that CircuitPython runs on boot.
#
# Responsibilities:
#   1. Initialise all hardware via the /API modules
#   2. Create the Model (game state) and View (display/audio)
#   3. Poll inputs every loop iteration:
#      - CapTouch pad (A5) toggles demo/manual mode
#      - IMU accelerometer tilt sets the snake direction
#   4. Advance the game (model.step()) at a fixed tick rate
#   5. Route events from the Model to the View:
#      - "ate_food" --> update score label + play eat sound
#      - "died"     --> play death sound + flash red + show overlay + reset
#      - None       --> just redraw the grid
#
# Data flow each loop iteration:
#
#   Hardware Inputs                      Screen / Audio / LEDs
#        |                                       ^
#        v                                       |
#   CONTROLLER                              CONTROLLER
#   poll_inputs()                           view.render()
#        |                                  view.play_sfx()
#        v                                       ^
#   MODEL                                        |
#   model.set_direction()                   event = model.step()
#   model.toggle_demo()                          |
#                                          (routes event to View)
#
# The Model never calls the View.  The View never reads inputs.
# All communication flows through the Controller.

import sys
import time

import supervisor
supervisor.runtime.autoreload = True     # auto-reload when code.py changes

# Add /API to the import path so we can use the hardware abstraction modules
sys.path.append("/API")

# -- Hardware abstraction modules (from /API) --------------------------------
from lcd_display import LCDDisplay    # ST7789 240x135 TFT LCD
from imu_sensor import IMUSensor      # ICM20948 accelerometer/gyro
from neopixels import NeoPixels       # NeoPixel RGB LED strip
from cap_touch import CapTouch        # Capacitive touch pad (A5)
from audio_out import AudioOutput     # DAC audio output
from digital_io import DigitalOutput  # On-board LED
import board

# -- MVC modules (from D:/ root alongside this file) ------------------------
from snake_model import SnakeModel, UP, DOWN, LEFT, RIGHT
from snake_view import SnakeView

# =============================================================================
# HARDWARE INITIALISATION
# =============================================================================
# Each API module wraps the underlying CircuitPython library so we do not
# need to deal with pins, SPI buses, or I2C addresses directly.

lcd = LCDDisplay()                              # LCD display (SPI + backlight)
imu = IMUSensor()                               # 9-axis IMU (I2C)
px  = NeoPixels(num_pixels=1, brightness=0.2)   # single mode-indicator LED
pad = CapTouch()                                # capacitive touch pad on A5

# The on-board LED might not exist on every board variant
try:
    led = DigitalOutput(board.LED)
except Exception:
    led = None

audio = AudioOutput()    # DAC audio for sound effects

# =============================================================================
# CREATE MVC OBJECTS
# =============================================================================
# The Model is created first (pure data, no hardware).
# The View is created second, receiving hardware references it needs.
# The Controller (this file) holds references to both.

model = SnakeModel()
view  = SnakeView(lcd.display, px, led, audio)

# Set initial View state to match the Model
view.update_score(model.score)        # show "0" in the score label
view.set_mode_pixel(model.demo_mode)  # blue = manual mode

# =============================================================================
# INPUT PROCESSING
# =============================================================================
# The IMU returns raw acceleration in m/s^2.  We apply a low-pass filter
# (exponential moving average) to smooth out noise and vibration, then
# compare the filtered values against a threshold to determine tilt direction.

TILT_THRESH = 2.2     # minimum filtered acceleration to register as a tilt
LPF_ALPHA   = 0.25    # low-pass filter smoothing factor (0 = no change, 1 = raw)
ax_f = 0.0            # filtered X acceleration (running average)
ay_f = 0.0            # filtered Y acceleration (running average)


def poll_inputs():
    """Read all hardware inputs and push changes into the Model.

    Called every loop iteration (~5 ms).  This is faster than the game
    tick rate (120 ms) so that input feels responsive -- we sample the
    tilt many times per tick but only move the snake once per tick.
    """
    global ax_f, ay_f

    # -- Capacitive touch: toggle demo mode on tap --------------------------
    # pad.update() must be called every iteration to detect edges.
    # pad.just_touched is True for exactly one iteration when a tap begins.
    pad.update()
    if pad.just_touched:
        is_demo = model.toggle_demo()       # flip the Model flag
        view.set_mode_pixel(is_demo)         # tell View to change LED colour
        view.flash_led(3)                    # blink LED as tactile feedback
        print("DEMO_MODE:", is_demo)

    # In demo mode the AI controls direction -- skip IMU reading
    if model.demo_mode:
        return

    # -- IMU tilt: steer the snake ------------------------------------------
    # Read raw acceleration (m/s^2) from the ICM20948
    ax, ay, _ = imu.acceleration

    # Apply exponential moving average low-pass filter to reduce noise.
    # ax_f tracks the smoothed X-axis tilt, ay_f tracks Y-axis.
    ax_f = (1.0 - LPF_ALPHA) * ax_f + LPF_ALPHA * ax
    ay_f = (1.0 - LPF_ALPHA) * ay_f + LPF_ALPHA * ay

    # Determine which axis has the stronger tilt
    absx = abs(ax_f)
    absy = abs(ay_f)

    # Convert tilt to a direction -- only if above the dead-zone threshold
    new_dir = None
    if absx >= absy and absx > TILT_THRESH:
        # Horizontal tilt dominates
        new_dir = RIGHT if ax_f > 0 else LEFT
    elif absy > TILT_THRESH:
        # Vertical tilt dominates
        new_dir = UP if ay_f > 0 else DOWN

    # Push the direction into the Model (it will reject 180-degree reversals)
    if new_dir is not None:
        model.set_direction(new_dir)


# =============================================================================
# MAIN GAME LOOP
# =============================================================================
# The loop runs as fast as possible (~5 ms sleep per iteration) but only
# advances the game state at a fixed tick rate (TICK_S = 0.12 seconds).
# This gives ~8.3 game ticks per second -- a comfortable Snake speed.

TICK_S    = 0.12     # seconds between game ticks (snake moves)
last_tick = 0.0      # timestamp of the last game tick

while True:
    # Always poll inputs -- this must be fast and non-blocking
    poll_inputs()

    # Check if it is time for the next game tick
    now = time.monotonic()
    if now - last_tick >= TICK_S:
        last_tick = now

        # Advance the Model by one tick and get the resulting event
        event = model.step()

        # -- Route the event to the View ------------------------------------
        if event == "ate_food":
            # Snake ate food: update the score display
            view.update_score(model.score)
            # Play the eating sound (only in manual mode -- demo is silent)
            if not model.demo_mode:
                view.play_food_sfx()

        elif event == "died":
            # Snake died: play sound, flash, show overlay, then reset
            if not model.demo_mode:
                view.play_gameover_sfx()
            view.flash_red()                                    # brief red flash
            view.show_game_over(model.score, model.high_score)  # 3s overlay
            # Reset the Model for a new game
            model.reset(reset_score=not model.demo_mode)
            view.update_score(model.score)

        # Redraw the grid every tick (whether or not an event occurred)
        view.render(model)

    # Short sleep to avoid busy-spinning and give CircuitPython time
    # for USB, display refresh, and other background tasks
    time.sleep(0.005)
