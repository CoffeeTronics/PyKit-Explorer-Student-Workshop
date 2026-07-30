# Snake Game - Unified Launcher Integration

import time
import board

from base_game import BaseGame
from cap_touch import CapTouch
from digital_io import DigitalOutput

from games.snake.model import SnakeModel, UP, DOWN, LEFT, RIGHT
from games.snake.view import SnakeView


class SnakeGame(BaseGame):

    NAME = "Snake"
    HIGH_SCORE_SLOT = 0

    def setup(self):
        self.pad = CapTouch()
        try:
            self.led = DigitalOutput(board.LED)
        except Exception:
            self.led = None

        high_score = self.get_high_score()
        self.model = SnakeModel(high_score=high_score)
        self.view = SnakeView(self.lcd.display, self.px, self.led, self.audio)

        self._ax_f = 0.0
        self._ay_f = 0.0
        self._last_tick = 0.0
        self._in_menu = True  # Start in menu state (splash shown automatically)
        self._wait_for_tilt = False  # Wait for tilt after losing a life

    def run(self, switch_detector):
        TILT_THRESH = 2.2
        TILT_CENTER = 1.0  # Must be below this to "center" before tilting again
        LPF_ALPHA = 0.25
        TICK_S = 0.12

        while True:
            switch_detector.update()
            if switch_detector.fell:
                self._save_score()
                return True

            # Menu state: wait for tilt to start
            if self._in_menu:
                self.view.blink_start_prompt()
                ax, ay, _ = self.imu.acceleration
                if abs(ax) > TILT_THRESH or abs(ay) > TILT_THRESH:
                    self._in_menu = False
                    self.view.hide_start_menu()
                    self.view.update_score(self.model.score)
                    self.view.update_neopixels(self.model)
                    self.view.render(self.model)
                    time.sleep(0.2)
                    continue
                time.sleep(0.033)
                continue

            # Wait for player to tilt after losing a life
            if self._wait_for_tilt:
                ax, ay, _ = self.imu.acceleration
                if abs(ax) > TILT_THRESH or abs(ay) > TILT_THRESH:
                    self._wait_for_tilt = False
                    self._last_tick = time.monotonic()  # Reset tick timer
                time.sleep(0.033)
                continue

            self._poll_inputs(TILT_THRESH, LPF_ALPHA)

            now = time.monotonic()
            if now - self._last_tick >= TICK_S:
                self._last_tick = now
                event = self.model.step()

                if event == "ate_food":
                    self.view.update_score(self.model.score)
                    self.view.update_neopixels(self.model)
                    if not self.model.demo_mode:
                        self.view.play_food_sfx()
                        self._save_score()

                elif event == "hit":
                    # Lost a life but not game over
                    self.view.flash_red()
                    self.view.flash_neopixels_hit()
                    if not self.model.demo_mode:
                        self.view.play_gameover_sfx()
                    time.sleep(1.0)  # Let audio play
                    self.view.update_neopixels(self.model)
                    self.view.render(self.model)
                    self._wait_for_tilt = True  # Wait for tilt to resume

                elif event == "game_over":
                    if not self.model.demo_mode:
                        self.view.play_gameover_sfx()
                    self.view.flash_red()
                    self.view.flash_neopixels_gameover()
                    self.view.show_game_over(self.model.score, self.model.high_score)
                    self._save_score()
                    # Return to launcher after game over
                    return True

                self.view.render(self.model)

            time.sleep(0.005)

    def _poll_inputs(self, tilt_thresh, lpf_alpha):
        self.pad.update()
        if self.pad.just_touched:
            is_demo = self.model.toggle_demo()
            self.view.set_mode_pixel(is_demo)
            self.view.flash_led(3)

        if self.model.demo_mode:
            return

        ax, ay, _ = self.imu.acceleration
        self._ax_f = (1.0 - lpf_alpha) * self._ax_f + lpf_alpha * ax
        self._ay_f = (1.0 - lpf_alpha) * self._ay_f + lpf_alpha * ay

        absx = abs(self._ax_f)
        absy = abs(self._ay_f)

        new_dir = None
        if absx >= absy and absx > tilt_thresh:
            new_dir = RIGHT if self._ax_f > 0 else LEFT
        elif absy > tilt_thresh:
            new_dir = UP if self._ay_f > 0 else DOWN

        if new_dir is not None:
            self.model.set_direction(new_dir)

    def _save_score(self):
        if self.model.score > self.get_high_score():
            self.set_high_score(self.model.score)

    def cleanup(self):
        if self.pad:
            self.pad.deinit()
        if self.led:
            self.led.deinit()
        if hasattr(self, "view"):
            self.view.cleanup()
        self.audio.unload_all()
        self.audio.stop()
        self.px.off()
