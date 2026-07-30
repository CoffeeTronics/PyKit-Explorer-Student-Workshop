# Space Impact Game - Unified Launcher Integration
#
# Classic side-scrolling shooter controlled by tilting the board.
# D3 = fire, CAP1 = special weapon

import time
import gc
import board
import digitalio
import touchio
import displayio
import terminalio
from adafruit_display_text import label as _label

from base_game import BaseGame
from games.space_impact.model import SpaceModel, InputState
from games.space_impact.view import SpaceView

TILT_DEADZONE = 0.4
TILT_MAX = 3.0

STATE_MENU = 0
STATE_PLAYING = 1
STATE_GAMEOVER = 2
STATE_VICTORY = 3


class SpaceImpactGame(BaseGame):

    NAME = "Space Impact"
    HIGH_SCORE_SLOT = 1

    def setup(self):
        gc.collect()
        print(f"SpaceImpact setup start RAM: {gc.mem_free()}")

        self._show_startup_text(["Place Ruler flat.", "IMU Calibration", "starting..."])
        self.imu.calibrate(samples=30)
        self._show_startup_text(["IMU Calibration", "Completed"])
        time.sleep(0.5)

        self._btn = digitalio.DigitalInOut(board.D3)
        self._btn.direction = digitalio.Direction.INPUT
        self._btn.pull = digitalio.Pull.UP
        self._prev_btn = True
        self._btn_held = False
        self._buf_frames = 0

        try:
            self._touch = touchio.TouchIn(board.CAP1)
            self._has_touch = True
        except Exception:
            self._has_touch = False
            self._touch = None

        self._touch_stable = False
        self._touch_off_count = 0
        self._prev_touch = False
        self._input_state = InputState()

        gc.collect()
        print(f"Before model/view RAM: {gc.mem_free()}")

        self.model = SpaceModel()
        gc.collect()
        print(f"After model RAM: {gc.mem_free()}")

        self.view = SpaceView(self.lcd.display, self.px, self.audio)
        gc.collect()
        print(f"After view RAM: {gc.mem_free()}")

        self._state = STATE_MENU
        self._gameover_time = 0
        self._frame = 0

        self.model.high_score = self.get_high_score()
        self.px.fill((0, 0, 0))
        # Splash screen is shown automatically by view

        gc.collect()
        print(f"SpaceImpact setup done RAM: {gc.mem_free()}")

    def run(self, switch_detector):
        while True:
            switch_detector.update()
            if switch_detector.fell:
                self._save_score()
                return True

            self._poll_button()
            input_state = self._read_inputs()

            if self._state == STATE_MENU:
                self.view.blink_start_prompt()
                if input_state.fire:
                    self.model.reset()
                    self.view.hide_start_menu()
                    self.view.hide_overlays()
                    self._state = STATE_PLAYING
                    self._frame = 0
                    time.sleep(0.2)
                    continue
                time.sleep(0.033)
                continue

            if self._state == STATE_GAMEOVER:
                # Wait for audio to finish, with a minimum wait time
                elapsed = time.monotonic() - self._gameover_time
                audio_done = not self.view.is_audio_playing()
                if elapsed >= 1.0 and audio_done:
                    self.view.stop_audio()
                    self.px.fill((0, 0, 0))
                    return True  # Return to launcher
                time.sleep(0.033)
                continue

            if self._state == STATE_VICTORY:
                if input_state.fire:
                    self.view.stop_audio()
                    self.px.fill((0, 0, 0))
                    return True  # Return to launcher
                time.sleep(0.033)
                continue

            events = self.model.update(input_state)

            for event in events:
                if event == "fired":
                    self.view.play_sfx("shoot")
                elif event == "special_fired":
                    self.view.play_sfx("shoot")
                elif event == "enemy_destroyed":
                    self.view.play_sfx("explosion")
                elif event == "boss_hit":
                    self.view.play_sfx("explosion")
                elif event == "boss_destroyed":
                    self.view.play_sfx("explosion")
                elif event == "player_hit":
                    self.view.play_sfx("explosion")
                elif event == "shield_hit":
                    self.view.play_sfx("explosion")
                elif event == "powerup_collected":
                    self.view.play_sfx("shoot")
                elif event == "level_complete":
                    self.view.play_sfx("gameover")
                    self.view.show_victory(self.model.score, self.model.level)
                elif event == "level_reset":
                    self.view.hide_overlays()
                elif event == "all_clear":
                    self.view.play_sfx("gameover")
                    self.view.show_all_clear(self.model.score)
                    self._state = STATE_VICTORY
                    self._save_score()
                elif event == "gameover":
                    self.view.play_sfx("gameover")
                    self.view.show_game_over()
                    self.view.flash_neopixels_gameover()
                    self._state = STATE_GAMEOVER
                    self._gameover_time = time.monotonic()
                    self._save_score()

            if self._state == STATE_PLAYING:
                self.view.draw(self.model)
                self.view.update_neopixels(self.model)

            self._frame += 1
            if self._frame % 90 == 0:
                gc.collect()

            time.sleep(0.033)

    def _poll_button(self):
        current = not self._btn.value
        if current and not self._prev_btn:
            self._buf_frames = 3
        self._btn_held = current
        self._prev_btn = current

    def _read_inputs(self):
        ax, ay, _ = self.imu.calibrated_acceleration

        if abs(ax) < TILT_DEADZONE:
            self._input_state.tilt_x = 0.0
        elif ax > 0:
            self._input_state.tilt_x = min(1.0, (ax - TILT_DEADZONE) / TILT_MAX)
        else:
            self._input_state.tilt_x = max(-1.0, (ax + TILT_DEADZONE) / TILT_MAX)

        adj_y = -ay
        if abs(adj_y) < TILT_DEADZONE:
            self._input_state.tilt_y = 0.0
        elif adj_y > 0:
            self._input_state.tilt_y = min(1.0, (adj_y - TILT_DEADZONE) / TILT_MAX)
        else:
            self._input_state.tilt_y = max(-1.0, (adj_y + TILT_DEADZONE) / TILT_MAX)

        current = not self._btn.value
        if current and not self._prev_btn:
            self._buf_frames = 3
        self._btn_held = current
        self._prev_btn = current

        if self._btn_held or self._buf_frames > 0:
            self._input_state.fire = True
            if self._buf_frames > 0:
                self._buf_frames -= 1
        else:
            self._input_state.fire = False

        raw_touch = self._touch.value if self._has_touch else False
        if raw_touch:
            self._touch_stable = True
            self._touch_off_count = 0
        else:
            self._touch_off_count += 1
            if self._touch_off_count >= 3:
                self._touch_stable = False

        if self._touch_stable and not self._prev_touch:
            self._input_state.special = True
        else:
            self._input_state.special = False
        self._prev_touch = self._touch_stable

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

