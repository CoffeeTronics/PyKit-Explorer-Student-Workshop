# view.py - Snake Game View (MVC pattern)
#
# The View handles ALL output: LCD screen, audio, LEDs.
# It knows NOTHING about game rules.

import time
import gc
import displayio
import terminalio
import adafruit_imageload
from adafruit_display_text import bitmap_label

from lcd_display import WIDTH, HEIGHT
from neopixels import Colors
from games.snake.model import GRID_W, GRID_H

_BG    = 0
_SNAKE = 1
_FOOD  = 2
_HEAD  = 3

# Sound effect paths for preloading
_SOUND_PATHS = {
    "food": "/AudioFiles/210.wav",
    "hit": "/AudioFiles/140.wav",
    "gameover": "/AudioFiles/Snake_Game_Over_Jingle_Alt.wav",
}

try:
    from vectorio import Rectangle as VRectangle
    _use_vectorio = True
except Exception:
    _use_vectorio = False


class SnakeView:
    """All visual and audio output for the Snake game."""

    def __init__(self, display, px, led, audio):
        self._display = display
        self._px  = px
        self._led = led
        self._audio = audio
        self._game_initialized = False

        # --- Root displayio group ---
        self._root = displayio.Group()
        display.root_group = self._root

        # Load splash screen FIRST before any heavy allocations
        gc.collect()
        self._splash_group = displayio.Group()
        self._root.append(self._splash_group)

        try:
            bmp, pal = adafruit_imageload.load(
                "/Sprites/snake_splash.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self._splash_group.append(
                displayio.TileGrid(bmp, pixel_shader=pal, x=0, y=0))
            print("Snake splash image loaded")
        except Exception as e:
            print(f"Snake splash load failed: {e}")
            bg_bmp = displayio.Bitmap(WIDTH, HEIGHT, 1)
            bg_pal = displayio.Palette(1); bg_pal[0] = 0x101018
            self._splash_group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
            self._splash_group.append(bitmap_label.Label(
                terminalio.FONT, text="SNAKE",
                color=0x33FF55, scale=4,
                anchor_point=(0.5, 0.5),
                anchored_position=(WIDTH // 2, HEIGHT // 2 - 20)))

        # Blinking prompt on splash
        self._splash_prompt = bitmap_label.Label(
            terminalio.FONT, text="TILT TO START",
            color=0xFFFF00, scale=2,
            anchor_point=(0.5, 0.5),
            anchored_position=(WIDTH // 2, HEIGHT - 20))
        self._splash_group.append(self._splash_prompt)
        self._blink_counter = 0

    def init_game_graphics(self):
        """Initialize game graphics after splash is dismissed."""
        if self._game_initialized:
            return

        # Remove splash screen and free memory
        while len(self._splash_group):
            self._splash_group.pop()
        self._root.remove(self._splash_group)
        self._splash_group = None
        self._splash_prompt = None
        gc.collect()
        print(f"After splash release RAM: {gc.mem_free()}")

        # Now load game resources
        self._preload_sounds()

        self._scale = max(1, min(WIDTH // GRID_W, HEIGHT // GRID_H))

        self._bitmap = displayio.Bitmap(GRID_W, GRID_H, 4)
        self._palette = displayio.Palette(4)
        self._palette[_BG]    = 0x101018
        self._palette[_SNAKE] = 0x33FF55
        self._palette[_FOOD]  = 0xFF3355
        self._palette[_HEAD]  = 0x00DDFF

        tg = displayio.TileGrid(self._bitmap, pixel_shader=self._palette)

        self._game_layer = displayio.Group(
            scale=self._scale,
            x=(WIDTH  - GRID_W * self._scale) // 2,
            y=(HEIGHT - GRID_H * self._scale) // 2,
        )
        self._game_layer.append(tg)

        self._root.append(self._game_layer)

        self._ui = displayio.Group()
        self._root.append(self._ui)

        self._add_border()

        self._score_label = bitmap_label.Label(
            terminalio.FONT,
            text="0",
            color=0xFFFFFF,
            scale=2,
            anchor_point=(1.0, 0.0),
            anchored_position=(WIDTH - 2, 2),
        )
        self._ui.append(self._score_label)

        self._game_initialized = True
        gc.collect()
        print(f"Game graphics initialized RAM: {gc.mem_free()}")

    def _preload_sounds(self):
        """Preload all sound effects using the shared audio API."""
        if self._audio is None:
            return
        for name, path in _SOUND_PATHS.items():
            try:
                self._audio.preload_wav(name, path)
            except Exception as e:
                print(f"Failed to preload {name}: {e}")

    def render(self, model):
        """Redraw the game grid from Model state."""
        bmp = self._bitmap
        for y in range(GRID_H):
            for x in range(GRID_W):
                bmp[x, y] = _BG
        bmp[model.food[0], model.food[1]] = _FOOD
        for i, (x, y) in enumerate(model.snake):
            bmp[x, y] = _HEAD if i == 0 else _SNAKE

    def update_score(self, score):
        self._score_label.text = str(score)

    def flash_red(self, duration=0.15):
        old_bg = self._palette[_BG]
        self._palette[_BG] = 0xFF0000
        for y in range(GRID_H):
            for x in range(GRID_W):
                self._bitmap[x, y] = _BG
        time.sleep(duration)
        self._palette[_BG] = old_bg

    def show_game_over(self, score, high_score, duration=3.0):
        # Release resources to free memory for game over BMP
        self._release_for_gameover()

        gc.collect()
        print(f"Snake game over RAM: {gc.mem_free()}")

        # Create fresh root for game over screen
        self._root = displayio.Group()
        self._display.root_group = self._root

        overlay = displayio.Group()

        # Try to load game over image
        try:
            bmp, pal = adafruit_imageload.load(
                "/Sprites/Game_Over_Snake.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            overlay.append(displayio.TileGrid(bmp, pixel_shader=pal, x=0, y=0))
        except Exception:
            # Fallback to text
            bg_bmp = displayio.Bitmap(WIDTH, HEIGHT, 1)
            bg_pal = displayio.Palette(1); bg_pal[0] = 0x101018
            overlay.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
            title = bitmap_label.Label(
                terminalio.FONT,
                text="Game Over",
                color=0xFF3355,
                scale=4,
                anchor_point=(0.5, 0.5),
                anchored_position=(WIDTH // 2, HEIGHT // 2 - 14),
            )
            overlay.append(title)

        # Score overlay on top of image
        stats = bitmap_label.Label(
            terminalio.FONT,
            text=f"Score: {score}   High: {high_score}",
            color=0xFFFFFF,
            scale=2,
            anchor_point=(0.5, 0.5),
            anchored_position=(WIDTH // 2, HEIGHT - 20),
        )
        overlay.append(stats)

        self._root.append(overlay)
        time.sleep(duration)
        self._root.remove(overlay)

    def _release_for_gameover(self):
        """Release display resources to free memory for game over BMP."""
        # Remove splash group if still present
        if self._splash_group is not None:
            try:
                self._root.remove(self._splash_group)
            except ValueError:
                pass
            while len(self._splash_group):
                self._splash_group.pop()
            self._splash_group = None

        # Release game grid bitmap
        if hasattr(self, '_bitmap'):
            self._bitmap = None
            self._palette = None

        # Clear the tile grid
        if hasattr(self, '_tile'):
            try:
                self._root.remove(self._tile)
            except ValueError:
                pass
            self._tile = None

        # Release score label
        if hasattr(self, '_score_lbl'):
            try:
                self._root.remove(self._score_lbl)
            except ValueError:
                pass
            self._score_lbl = None

        # Don't unload audio - gameover sound needs to keep playing

        gc.collect()

    def set_mode_pixel(self, demo_mode):
        self._px.fill(Colors.GREEN if demo_mode else Colors.BLUE)

    def update_neopixels(self, model):
        """Update the 5 NeoPixels to reflect current game state.

        Pixel mapping:
          0   : demo mode indicator (green = demo, blue = playing)
          1-3 : lives (green = still alive, off = lost that life)
          4   : food indicator (red flash when near food, off otherwise)
        """
        if self._px is None:
            return

        # Pixel 0: demo/play mode
        self._px[0] = 0x00FF00 if model.demo_mode else 0x0000FF

        # Pixels 1-3: lives
        for i in range(3):
            if i < model.lives:
                self._px[i + 1] = 0x00FF00  # green per remaining life
            else:
                self._px[i + 1] = 0x000000  # off for lost lives

        # Pixel 4: score indicator (brighter with higher score)
        score_brightness = min(255, model.score * 20)
        self._px[4] = (score_brightness << 8)  # green intensity based on score

        self._px.show()

    def flash_neopixels_hit(self):
        """Flash NeoPixels red briefly when hit."""
        if self._px is not None:
            self._px.fill(0xFF0000)
            self._px.show()

    def flash_neopixels_gameover(self):
        """Set all 5 NeoPixels to red on game over."""
        if self._px is not None:
            self._px.fill(0xFF0000)
            self._px.show()

    # -------------------------------------------------------------------------
    # Start menu (splash screen)
    # -------------------------------------------------------------------------
    def show_start_menu(self):
        """Splash is shown by default in __init__, this is a no-op."""
        pass

    def hide_start_menu(self):
        """Dismiss splash and initialize game graphics."""
        self.init_game_graphics()

    def blink_start_prompt(self):
        """Call every frame while the splash screen is visible."""
        if self._splash_prompt is None:
            return
        self._blink_counter += 1
        if self._blink_counter >= 30:
            self._blink_counter = 0
        self._splash_prompt.hidden = (self._blink_counter >= 15)

    def flash_led(self, n=3, on_s=0.05, off_s=0.05):
        if self._led:
            self._led.blink(on_time=on_s, off_time=off_s, count=n)

    def play_food_sfx(self):
        if self._audio:
            self._audio.play_preloaded("food")

    def play_hit_sfx(self):
        """Play sound for losing a life (not final death)."""
        if self._audio:
            self._audio.play_preloaded("hit")

    def play_gameover_sfx(self):
        """Play sound for final death (game over)."""
        if self._audio:
            self._audio.play_preloaded("gameover")

    def is_audio_playing(self):
        """Check if audio is currently playing."""
        if self._audio:
            return self._audio.is_playing
        return False

    def cleanup(self):
        """Release view resources."""
        self._px.off()

    def _add_border(self):
        w_px = GRID_W * self._scale
        h_px = GRID_H * self._scale
        x0 = self._game_layer.x
        y0 = self._game_layer.y
        color = 0x00FF00

        border = displayio.Group()
        if _use_vectorio:
            pal = displayio.Palette(1); pal[0] = color
            border.append(VRectangle(pixel_shader=pal, x=x0,        y=y0 - 1,    width=w_px, height=1))
            border.append(VRectangle(pixel_shader=pal, x=x0,        y=y0 + h_px, width=w_px, height=1))
            border.append(VRectangle(pixel_shader=pal, x=x0 - 1,    y=y0,        width=1,    height=h_px))
            border.append(VRectangle(pixel_shader=pal, x=x0 + w_px, y=y0,        width=1,    height=h_px))
        else:
            pal = displayio.Palette(1); pal[0] = color
            top    = displayio.Bitmap(w_px, 1, 1)
            bottom = displayio.Bitmap(w_px, 1, 1)
            left   = displayio.Bitmap(1, h_px, 1)
            right  = displayio.Bitmap(1, h_px, 1)
            for x in range(w_px):
                top[x, 0] = 0;    bottom[x, 0] = 0
            for y in range(h_px):
                left[0, y] = 0;   right[0, y] = 0
            border.append(displayio.TileGrid(top,    pixel_shader=pal, x=x0,        y=y0 - 1))
            border.append(displayio.TileGrid(bottom, pixel_shader=pal, x=x0,        y=y0 + h_px))
            border.append(displayio.TileGrid(left,   pixel_shader=pal, x=x0 - 1,    y=y0))
            border.append(displayio.TileGrid(right,  pixel_shader=pal, x=x0 + w_px, y=y0))

        self._root.append(border)
