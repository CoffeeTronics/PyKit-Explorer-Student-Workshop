# Super Mario Bros Game - Unified Launcher Integration
#
# Classic platformer controlled by tilting the board.
# D3 = jump, CAP1 = run

import time
import gc
import board
import digitalio
import touchio
import displayio
import terminalio
from adafruit_display_text import label as _label

from base_game import BaseGame
from games.mario.model import MarioModel, InputState
from games.mario.view import MarioView

TILT_DEADZONE = 0.8
TILT_MAX = 6.0


class MarioGame(BaseGame):

    NAME = "Super Mario"
    HIGH_SCORE_SLOT = 2

    def setup(self):
        self._show_startup_text(["Place Ruler flat.", "IMU Calibration", "starting..."])
        self.imu.calibrate(samples=30)
        self._show_startup_text(["IMU Calibration", "Completed"])
        time.sleep(0.5)

        self._btn = digitalio.DigitalInOut(board.D3)
        self._btn.direction = digitalio.Direction.INPUT
        self._btn.pull = digitalio.Pull.UP
        self._prev_btn = True
        self._buf_frames = 0

        try:
            self._touch = touchio.TouchIn(board.CAP1)
            self._has_touch = True
        except Exception:
            self._has_touch = False
            self._touch = None

        self._run_stable = False
        self._run_off_count = 0
        self._input_state = InputState()

        self.model = MarioModel()
        self.view = MarioView(self.lcd.display, self.px, self.audio)

        self._frame = 0
        self._gameover_holding = False
        self._in_menu = True  # Start in menu state (splash shown automatically)

        self.model.high_score = self.get_high_score()
        self.px.fill((0, 0, 0))

    def run(self, switch_detector):
        while True:
            switch_detector.update()
            if switch_detector.fell:
                self._save_score()
                return True

            self._poll_button()
            input_state = self._read_inputs()

            # Menu state: wait for jump or run button
            if self._in_menu:
                self.view.blink_start_prompt()
                # Check for jump button (D3) or run touch (CAP1)
                jump_pressed = not self._btn.value
                run_pressed = self._touch.value if self._has_touch else False
                if jump_pressed or run_pressed:
                    self._in_menu = False
                    self.view.hide_start_menu()
                    self.model.reset()
                    self._frame = 0
                    time.sleep(0.2)
                    continue
                time.sleep(0.033)
                continue

            events = self.model.update(input_state)

            for event in events:
                if event == "jumped":
                    self.view.play_sfx("jump")
                elif event == "coin":
                    self.view.play_sfx("coin")
                elif event == "gameover":
                    self.view.play_sfx("gameover")
                    self.view.show_game_over()
                    self.view.flash_neopixels_gameover()
                    self._gameover_holding = False
                    self._save_score()
                elif event == "level_complete":
                    self.view.play_sfx("world_clear")
                    self.view.show_victory(self.model.score, self.model.coins)
                    self._save_score()
                elif event == "level_reset":
                    self.view.hide_overlays()

            if not self.model.game_over:
                self.view.draw(self.model)
                self.view.update_neopixels(self.model, self.model.level_complete)

            self._frame += 1

            if self._frame % 90 == 0:
                gc.collect()

            if self.model.game_over and not self._gameover_holding:
                self._gameover_holding = True
                for i in range(150):
                    switch_detector.update()
                    if switch_detector.fell:
                        self._save_score()
                        return True
                    time.sleep(0.033)

                self.view.stop_audio()
                self.px.fill((0, 0, 0))
                return True  # Return to launcher

            time.sleep(0.033)

    def _poll_button(self):
        current = not self._btn.value
        if current and not self._prev_btn:
            self._buf_frames = 3
        self._prev_btn = current

    def _read_inputs(self):
        ax, _, _ = self.imu.calibrated_acceleration

        if abs(ax) < TILT_DEADZONE:
            self._input_state.tilt_value = 0.0
        elif ax > 0:
            self._input_state.tilt_value = min(1.0, (ax - TILT_DEADZONE) / TILT_MAX)
        else:
            self._input_state.tilt_value = max(-1.0, (ax + TILT_DEADZONE) / TILT_MAX)

        current = not self._btn.value
        if current and not self._prev_btn:
            self._buf_frames = 3
        self._prev_btn = current

        if self._buf_frames > 0:
            self._input_state.jump = True
            self._buf_frames -= 1
        else:
            self._input_state.jump = False

        raw_run = self._touch.value if self._has_touch else False
        if raw_run:
            self._run_stable = True
            self._run_off_count = 0
        else:
            self._run_off_count += 1
            if self._run_off_count >= 3:
                self._run_stable = False
        self._input_state.run = self._run_stable

        return self._input_state

    def _show_startup_text(self, lines):
        grp = displayio.Group()
        bg_bmp = displayio.Bitmap(240, 135, 1)
        bg_pal = displayio.Palette(1)
        bg_pal[0] = 0x000000
        grp.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))

        row_h = 22
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

        self.lcd.display.root_group = grp

    def _save_score(self):
        if self.model.score > self.get_high_score():
            self.set_high_score(self.model.score)

    def cleanup(self):
        if self._btn:
            self._btn.deinit()
        if self._touch:
            self._touch.deinit()
        self.audio.unload_all()
        self.audio.stop()
        self.px.off()

