# snake_view.py - VIEW (MVC pattern)
#
# The View is responsible for ALL output: LCD screen, audio, LEDs.
# It knows NOTHING about game rules -- it simply draws whatever the
# Controller tells it to draw, and plays sounds when asked.
#
# What lives here:
#   - LCD bitmap surface (24x18 grid scaled to 240x135 pixels)
#   - Colour palette for background, snake body, head, and food
#   - Green border around the play area
#   - Score label (top-right corner)
#   - Game-over overlay (centred title + score + high score)
#   - Red flash death effect
#   - NeoPixel mode indicator (blue = manual, green = demo)
#   - LED blink for touch feedback
#   - Audio sound effects (food eaten, game over)
#
# How it communicates:
#   - The Controller calls render(model) each tick to redraw the grid.
#   - The Controller calls specific methods like flash_red(),
#     show_game_over(), play_food_sfx() when events occur.
#   - render() reads model.snake and model.food directly -- this is
#     the only place the View "sees" the Model, and it only reads.
import pykit_explorer
import displayio
import terminalio
from adafruit_display_text import bitmap_label

from lcd_display import WIDTH, HEIGHT           # 240, 135
from neopixels import Colors
from snake_model import GRID_W, GRID_H          # 24, 18

# Palette index constants -- used when painting cells in the bitmap.
# Index 0 = background, 1 = snake body, 2 = food, 3 = head.
_BG    = 0
_SNAKE = 1
_FOOD  = 2
_HEAD  = 3

# vectorio provides hardware-accelerated rectangles for the border.
# If it is not available (older CircuitPython), fall back to Bitmap tiles.
try:
    from vectorio import Rectangle as VRectangle
    _use_vectorio = True
except Exception:
    _use_vectorio = False


class SnakeView:
    """All visual and audio output for the Snake game.

    Constructor parameters (injected by the Controller):
        display -- the ST7789 display object from LCDDisplay.display
        px      -- NeoPixels instance (1 pixel, used as mode indicator)
        led     -- DigitalOutput for the on-board LED (or None)
        audio   -- AudioOutput instance for DAC sound effects

    displayio layer structure (back to front):
        _root
          +-- _game_layer   (scaled bitmap: 24x18 cells)
          +-- border_group  (4 thin green rectangles)
          +-- _ui           (score label, game-over overlay)
    """

    def __init__(self, display, px, led, audio):
        self._display = display
        self._px  = px      # NeoPixel strip (1 pixel) for mode colour
        self._led = led     # on-board LED for touch feedback blink
        self._audio = audio # AudioOutput for DAC playback

        # -- Pre-load WAV sound effects into memory --------------------------
        # We keep the file handles open for the lifetime of the program
        # so the WaveFile objects remain valid for repeated playback.
        self._sfx_food = None
        self._sfx_gameover = None
        try:
            from audiocore import WaveFile
            self._wav210_f = open("AudioFiles/210.wav", "rb")
            self._sfx_food = WaveFile(self._wav210_f)       # eating sound
            self._wav140_f = open("AudioFiles/140.wav", "rb")
            self._sfx_gameover = WaveFile(self._wav140_f)    # death sound
        except Exception as e:
            print("Audio init failed:", e)

        # -- Game bitmap surface ---------------------------------------------
        # Each cell in the 24x18 grid maps to one pixel in the bitmap.
        # The TileGrid scales it up so it fills most of the 240x135 LCD.
        # scale = min(240/24, 135/18) = min(10, 7) = 7 pixels per cell.
        self._scale = max(1, min(WIDTH // GRID_W, HEIGHT // GRID_H))

        # Create a small bitmap (24x18) with 4 colours (indexed palette)
        self._bitmap = displayio.Bitmap(GRID_W, GRID_H, 4)
        self._palette = displayio.Palette(4)
        self._palette[_BG]    = 0x101018   # dark blue-grey background
        self._palette[_SNAKE] = 0x33FF55   # bright green body
        self._palette[_FOOD]  = 0xFF3355   # red-pink food
        self._palette[_HEAD]  = 0x00DDFF   # cyan head

        # TileGrid renders the bitmap using the palette for colour lookup
        tg = displayio.TileGrid(self._bitmap, pixel_shader=self._palette)

        # Group with scale centres the game area on the LCD
        self._game_layer = displayio.Group(
            scale=self._scale,
            x=(WIDTH  - GRID_W * self._scale) // 2,
            y=(HEIGHT - GRID_H * self._scale) // 2,
        )
        self._game_layer.append(tg)

        # Root group is what the display actually renders
        self._root = displayio.Group()
        display.root_group = self._root
        self._root.append(self._game_layer)

        # UI overlay group sits on top for score and game-over text
        self._ui = displayio.Group()
        self._root.append(self._ui)

        # Draw the green border around the play area
        self._add_border()

        # -- Score label (top-right corner) ----------------------------------
        self._score_label = bitmap_label.Label(
            terminalio.FONT,     # built-in monospace font
            text="0",
            color=0xFFFFFF,      # white
            scale=2,             # 2x size for readability
            anchor_point=(1.0, 0.0),              # anchor to top-right
            anchored_position=(WIDTH - 2, 2),     # 2px from right edge
        )
        self._ui.append(self._score_label)

    # =========================================================================
    # PUBLIC DRAWING API -- called by the Controller
    # =========================================================================

    def render(self, model):
        """Redraw the entire game grid from the current Model state.

        Called every tick (0.12s).  Clears the bitmap, paints the food,
        then paints every snake segment.  The head gets a different
        colour (_HEAD = cyan) so the player can see which end is which.
        """
        bmp = self._bitmap
        # Clear the entire grid to background
        for y in range(GRID_H):
            for x in range(GRID_W):
                bmp[x, y] = _BG
        # Paint the food pellet
        bmp[model.food[0], model.food[1]] = _FOOD
        # Paint the snake -- head (index 0) in cyan, body in green
        for i, (x, y) in enumerate(model.snake):
            bmp[x, y] = _HEAD if i == 0 else _SNAKE

    def update_score(self, score):
        """Update the score text in the top-right corner."""
        self._score_label.text = str(score)

    def flash_red(self, duration=0.15):
        """Brief red flash effect when the snake dies.

        Temporarily swaps the background palette colour to red and
        clears the grid, then restores the original colour.
        """
        old_bg = self._palette[_BG]
        self._palette[_BG] = 0xFF0000      # swap background to red
        for y in range(GRID_H):
            for x in range(GRID_W):
                self._bitmap[x, y] = _BG   # fill with "background" = red
        time.sleep(duration)
        self._palette[_BG] = old_bg         # restore original background

    def show_game_over(self, score, high_score, duration=3.0):
        """Show a "Game Over" overlay with score for 3 seconds.

        Creates temporary text labels, appends them to the UI layer,
        waits, then removes them.  This blocks the game loop, which
        is intentional -- the player needs time to read the score.
        """
        overlay = displayio.Group()
        # Large "Game Over" title centred on screen
        title = bitmap_label.Label(
            terminalio.FONT,
            text="Game Over",
            color=0xFFFFFF,
            scale=4,
            anchor_point=(0.5, 0.5),
            anchored_position=(WIDTH // 2, HEIGHT // 2 - 14),
        )
        overlay.append(title)
        # Smaller score + high score below the title
        stats = bitmap_label.Label(
            terminalio.FONT,
            text=f"Score: {score}   High: {high_score}",
            color=0xFFFFFF,
            scale=2,
            anchor_point=(0.5, 0.0),
            anchored_position=(WIDTH // 2, HEIGHT // 2 + 8),
        )
        overlay.append(stats)
        self._ui.append(overlay)
        time.sleep(duration)
        self._ui.remove(overlay)    # clean up so it does not linger

    def set_mode_pixel(self, demo_mode):
        """Set the NeoPixel colour to indicate the current play mode.

        Blue  = manual play (player tilts the board)
        Green = demo mode (AI plays automatically)
        """
        self._px.fill(Colors.GREEN if demo_mode else Colors.BLUE)

    def flash_led(self, n=3, on_s=0.05, off_s=0.05):
        """Blink the on-board LED as tactile feedback for touch input."""
        if self._led:
            self._led.blink(on_time=on_s, off_time=off_s, count=n)

    # =========================================================================
    # AUDIO (private helper + public triggers)
    # =========================================================================

    def play_food_sfx(self):
        """Play the short 'eat' sound when the snake eats food."""
        self._play(self._sfx_food)

    def play_gameover_sfx(self):
        """Play the 'death' sound when the snake dies."""
        self._play(self._sfx_gameover)

    def _play(self, wav):
        """Fire-and-forget WAV playback via the DAC.

        Uses audio._audio (the raw AudioOut object) directly because
        AudioOutput.play_wav() blocks until the sound finishes, which
        would freeze the game loop.  This way the sound plays in the
        background while the game continues.
        """
        if wav is None or self._audio is None:
            return
        try:
            if self._audio.is_playing:
                self._audio.stop()           # stop any previous sound
            self._audio._audio.play(wav)     # non-blocking playback
        except Exception as e:
            print("Audio play error:", e)

    # =========================================================================
    # BORDER (private, called once during __init__)
    # =========================================================================

    def _add_border(self):
        """Draw a 1-pixel green border around the gameplay area.

        Uses vectorio Rectangles if available (faster, less RAM), or
        falls back to Bitmap-based TileGrids on older CircuitPython.
        """
        w_px = GRID_W * self._scale    # border width in real pixels
        h_px = GRID_H * self._scale    # border height in real pixels
        x0 = self._game_layer.x       # left edge of game area
        y0 = self._game_layer.y       # top edge of game area
        color = 0x00FF00               # green

        border = displayio.Group()
        if _use_vectorio:
            # vectorio: 4 thin rectangles (top, bottom, left, right)
            pal = displayio.Palette(1); pal[0] = color
            border.append(VRectangle(pixel_shader=pal, x=x0,        y=y0 - 1,    width=w_px, height=1))
            border.append(VRectangle(pixel_shader=pal, x=x0,        y=y0 + h_px, width=w_px, height=1))
            border.append(VRectangle(pixel_shader=pal, x=x0 - 1,    y=y0,        width=1,    height=h_px))
            border.append(VRectangle(pixel_shader=pal, x=x0 + w_px, y=y0,        width=1,    height=h_px))
        else:
            # Bitmap fallback: create 4 small bitmaps filled with colour 0
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
