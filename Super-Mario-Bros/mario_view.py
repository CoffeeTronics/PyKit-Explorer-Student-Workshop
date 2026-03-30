# mario_view.py - VIEW (MVC pattern)
#
# All visual and audio output for the Mario game.
# Reads model state to position sprites; never modifies game state.
#
# Constructor parameters (injected by the Controller):
#   display -- ST7789 display object (rotation / size already configured)
#   px      -- neopixel.NeoPixel strip (5 pixels, brightness pre-set)
#
# displayio layer structure (back to front):
#   main_group
#     +-- sky bitmap        (static blue background)
#     +-- ground bitmap     (static green strip)
#     +-- _sprite_group     (platforms, coins, enemies, Mario TileGrids)
#     +-- _hud              (SCORE / LIVES / COINS labels)
#     +-- _victory_screen   (level-complete overlay)
#     +-- _gameover_screen  (game-over overlay)
#
# Public API (called by the Controller):
#   draw(model)                  -- reposition all sprites each tick
#   play_sfx(name)               -- trigger a WAV sound effect
#   stop_audio()                 -- stop current playback
#   is_audio_playing()           -- True while a sound is active
#   show_victory(score, coins)   -- display level-complete overlay
#   show_game_over()             -- display game-over overlay
#   hide_overlays()              -- remove overlays, restore HUD
#   update_neopixels(model, ...)  -- set 5 NeoPixels to reflect game state
#   flash_neopixels_gameover()   -- turn all pixels red

import displayio
import adafruit_imageload
import terminalio
import gc

try:
    import audiocore
    import audioio
    _AUDIO_AVAILABLE = True
except ImportError:
    _AUDIO_AVAILABLE = False

from adafruit_display_text import label as _label

from mario_model import (
    DISPLAY_WIDTH, DISPLAY_HEIGHT, GROUND_Y,
    MARIO_WIDTH, MARIO_HEIGHT,
    ENEMY_WIDTH, ENEMY_HEIGHT,
    BLOCK_SIZE,
)


# ===========================================================================
# AudioManager (private helper)
# ===========================================================================
class _AudioManager:
    """Manage non-blocking WAV sound-effect playback.

    Opens and closes the WAV file on each play to keep RAM usage low.
    Re-initialises the AudioOut device every 50 plays to prevent memory
    fragmentation on CircuitPython's heap.
    """
    _SOUNDS = {
        "jump":        "/AudioFiles/smb_jump.wav",
        "coin":        "/AudioFiles/smb_coin.wav",
        "gameover":    "/AudioFiles/smb_gameover.wav",
        "world_clear": "/AudioFiles/smb_world_clear.wav",
    }
    _MIN_INTERVAL = 0.1   # minimum seconds between plays (rate limiter)
    _REINIT_EVERY = 50    # re-create AudioOut every N plays

    def __init__(self):
        self.enabled    = False
        self._audio     = None
        self._file      = None
        self._wave      = None
        self._last_t    = 0.0
        self._count     = 0
        self._available = {}   # name -> path for files found on disk

        if not _AUDIO_AVAILABLE:
            return
        try:
            import board
            self._audio  = audioio.AudioOut(board.DAC)
            self.enabled = True
            self._verify_files()
        except Exception as e:
            print(f"Audio init failed: {e}")

    def _verify_files(self):
        """Check which WAV files actually exist on the filesystem."""
        for name, path in self._SOUNDS.items():
            try:
                with open(path, "rb"):
                    pass
                self._available[name] = path
                print(f"  audio ok: {name}")
            except Exception:
                pass

    def play(self, sound_name: str):
        """Start playing a named sound effect (non-blocking)."""
        if not self.enabled or sound_name not in self._available:
            return
        import time
        now = time.monotonic()
        if now - self._last_t < self._MIN_INTERVAL:
            return
        try:
            self._cleanup()
            self._count += 1
            # Periodically re-create AudioOut to avoid heap fragmentation
            if self._count % self._REINIT_EVERY == 0:
                import board
                try:
                    self._audio.deinit()
                    self._audio = audioio.AudioOut(board.DAC)
                except Exception:
                    pass
            self._file  = open(self._available[sound_name], "rb")
            self._wave  = audiocore.WaveFile(self._file)
            self._audio.play(self._wave)
            self._last_t = now
        except Exception as e:
            print(f"Audio error ({sound_name}): {e}")
            self._cleanup()

    def stop(self):
        """Stop playback and release all audio resources."""
        self._cleanup()

    def is_playing(self) -> bool:
        """True if a sound is currently playing."""
        if self.enabled and self._audio:
            try:
                return self._audio.playing
            except Exception:
                pass
        return False

    def _cleanup(self):
        """Release the current WAV resources without triggering GC."""
        try:
            if self._audio and self._audio.playing:
                self._audio.stop()
        except Exception:
            pass
        try:
            if self._file is not None:
                self._file.close()
        except Exception:
            pass
        self._file = None
        self._wave = None


# ===========================================================================
# SpriteLoader (private helper)
# ===========================================================================
class _SpriteLoader:
    """Load all sprite sheets from /Sprites/ once at startup.

    If any sheet fails to load, `loaded` is set to False and the View
    falls back to solid-colour rectangles for all entities.
    """
    def __init__(self):
        self.loaded         = False
        self.mario_sheet    = None; self.mario_palette   = None
        self.goomba_sheet   = None; self.goomba_palette  = None
        self.block_sheet    = None; self.block_palette   = None
        self.coin_sheet     = None; self.coin_palette    = None
        self._load()

    def _load(self):
        try:
            self.mario_sheet,  self.mario_palette  = adafruit_imageload.load(
                "/Sprites/mario_sprites.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.goomba_sheet, self.goomba_palette = adafruit_imageload.load(
                "/Sprites/goomba_sprites.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.block_sheet,  self.block_palette  = adafruit_imageload.load(
                "/Sprites/block_sprites.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.coin_sheet,   self.coin_palette   = adafruit_imageload.load(
                "/Sprites/coin_sprite.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.loaded = True
            print("Sprites loaded OK")
        except Exception as e:
            print(f"Sprite load failed: {e} -- using coloured rectangles")


# ===========================================================================
# HUD (private helper)
# ===========================================================================
class _HUD:
    """Score, coins, and lives labels across the top of the screen.

    Only regenerates label strings when the underlying value changes,
    preventing string churn on CircuitPython's heap.
    """
    def __init__(self, parent_group):
        self._group = displayio.Group()
        parent_group.append(self._group)

        self._score = _label.Label(terminalio.FONT, text="SCORE: 0",
                                   color=0xFFFFFF, x=5,   y=8)
        self._lives = _label.Label(terminalio.FONT, text="LIVES: 3",
                                   color=0xFFFFFF, x=95,  y=8)
        self._coins = _label.Label(terminalio.FONT, text="COINS: 0",
                                   color=0xFFFFFF, x=175, y=8)
        for lbl in (self._score, self._lives, self._coins):
            self._group.append(lbl)

        # Cache last values so we skip string creation on unchanged fields
        self._last_score = -1
        self._last_lives = -1
        self._last_coins = -1

    def update(self, score: int, coins: int, lives: int):
        """Refresh labels only when values have changed."""
        if score != self._last_score:
            self._score.text = f"SCORE:{score}"
            self._last_score = score
        if coins != self._last_coins:
            self._coins.text = f"COINS:{coins}"
            self._last_coins = coins
        if lives != self._last_lives:
            self._lives.text = f"LIVES:{lives}"
            self._last_lives = lives

    def show(self):
        self._group.hidden = False

    def hide(self):
        self._group.hidden = True


# ===========================================================================
# VictoryScreen (private helper)
# ===========================================================================
class _VictoryScreen:
    """Level-complete overlay shown when Mario reaches the end flag.

    Displays a black background with "LEVEL COMPLETE!", final score,
    and coin count.  Hidden by default; shown via show().
    """
    def __init__(self, parent_group):
        self._group = displayio.Group()
        parent_group.append(self._group)

        # Solid black background fills the whole display
        bg_bmp = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
        bg_pal = displayio.Palette(1); bg_pal[0] = 0x000000
        self._group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))

        self._group.append(_label.Label(
            terminalio.FONT, text="LEVEL COMPLETE!",
            color=0xFFD700, scale=2, x=30, y=40))

        self._score_lbl = _label.Label(
            terminalio.FONT, text="SCORE: 0",
            color=0xFFFFFF, scale=2, x=50, y=70)
        self._group.append(self._score_lbl)

        self._coins_lbl = _label.Label(
            terminalio.FONT, text="COINS: 0",
            color=0xFFFFFF, scale=2, x=50, y=95)
        self._group.append(self._coins_lbl)

        self._group.hidden = True

    def show(self, score: int, coins: int):
        self._score_lbl.text  = f"SCORE: {score}"
        self._coins_lbl.text  = f"COINS: {coins}"
        self._group.hidden    = False

    def hide(self):
        self._group.hidden = True


# ===========================================================================
# GameOverScreen (private helper)
# ===========================================================================
class _GameOverScreen:
    """Game-over overlay.

    Tries to load /Sprites/Game_Over.BMP; falls back to a text label
    on a black background if the image is not present.
    """
    def __init__(self, parent_group):
        self._group = displayio.Group()
        parent_group.append(self._group)

        try:
            bmp, pal = adafruit_imageload.load(
                "/Sprites/Game_Over.BMP",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self._group.append(
                displayio.TileGrid(bmp, pixel_shader=pal, x=0, y=0))
            print("Game Over image loaded")
        except Exception:
            bg_bmp = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
            bg_pal = displayio.Palette(1); bg_pal[0] = 0x000000
            self._group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
            self._group.append(_label.Label(
                terminalio.FONT, text="GAME OVER",
                color=0xFF0000, scale=3,
                x=40, y=DISPLAY_HEIGHT // 2))

        self._group.hidden = True

    def show(self):
        self._group.hidden = False

    def hide(self):
        self._group.hidden = True


# ===========================================================================
# MarioView -- public class used by the Controller
# ===========================================================================
class MarioView:
    """All visual and audio output for the Mario game.

    Constructor parameters (injected by the Controller):
        display -- ST7789 display object (rotation/size already configured)
        px      -- neopixel.NeoPixel strip (5 pixels, brightness pre-set)

    The Controller calls draw(model) every tick.
    Events from MarioModel are routed here via play_sfx / show_* / hide_*.
    """

    # Maps Platform.block_type to a tile index in the block sprite sheet
    _TILE_MAP = {"brick": 0, "question": 1, "pipe": 2}

    def __init__(self, display, px):
        self._display = display
        self._px      = px           # NeoPixel strip (5 pixels)

        # Audio and sprite resources
        self._audio   = _AudioManager()
        self._sprites = _SpriteLoader()

        # --- Root displayio group --------------------------------------------
        self.main_group = displayio.Group()
        display.root_group = self.main_group

        # Static sky background (never redrawn -- prevents flicker)
        sky_bmp = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
        sky_pal = displayio.Palette(1); sky_pal[0] = 0x5C94FC
        self.main_group.append(
            displayio.TileGrid(sky_bmp, pixel_shader=sky_pal, x=0, y=0))

        # Static ground strip
        gnd_bmp = displayio.Bitmap(DISPLAY_WIDTH, 30, 1)
        gnd_pal = displayio.Palette(1); gnd_pal[0] = 0x00AA00
        self.main_group.append(
            displayio.TileGrid(gnd_bmp, pixel_shader=gnd_pal, x=0, y=GROUND_Y))

        # Sprite group for all moving entities
        self._sprite_group = displayio.Group()
        self.main_group.append(self._sprite_group)

        # Pre-allocate sprite pools
        self._build_sprite_pools()

        # HUD and screen overlays (always on top)
        self._hud        = _HUD(self.main_group)
        self._victory    = _VictoryScreen(self.main_group)
        self._game_over  = _GameOverScreen(self.main_group)

        # Optimisation: skip sprite property writes when nothing changed
        self._last_mario_frame = -1
        self._last_mario_flip  = None

    # -------------------------------------------------------------------------
    # Sprite pool construction
    # -------------------------------------------------------------------------

    def _make_sheet_sprite(self, sheet, palette, tw, th):
        """Create a 1-tile TileGrid from a sprite sheet (width=tw, height=th)."""
        return displayio.TileGrid(
            sheet, pixel_shader=palette,
            width=1, height=1,
            tile_width=tw, tile_height=th,
            x=0, y=0)

    def _make_rect_sprite(self, w, h, color):
        """Fallback: solid-colour rectangle TileGrid (no sprite sheet)."""
        bmp = displayio.Bitmap(w, h, 1)
        pal = displayio.Palette(1); pal[0] = color
        return displayio.TileGrid(bmp, pixel_shader=pal)

    def _build_sprite_pools(self):
        """Pre-allocate all sprite slots once at startup.

        Using fixed pools avoids runtime allocation, which would fragment
        CircuitPython's heap and degrade performance over time.
        Pool sizes:
          75 platform slots -- covers the densest visible section
          10 enemy slots
          20 coin slots
           1 Mario sprite
        """
        sl = self._sprites

        # Platform pool
        self._platform_sprites = []
        for _ in range(75):
            s = (self._make_sheet_sprite(
                     sl.block_sheet, sl.block_palette, BLOCK_SIZE, BLOCK_SIZE)
                 if sl.loaded else
                 self._make_rect_sprite(BLOCK_SIZE, BLOCK_SIZE, 0xD87850))
            s.hidden = True
            self._platform_sprites.append(s)
            self._sprite_group.append(s)

        # Enemy pool
        self._enemy_sprites = []
        for _ in range(10):
            s = (self._make_sheet_sprite(
                     sl.goomba_sheet, sl.goomba_palette, ENEMY_WIDTH, ENEMY_HEIGHT)
                 if sl.loaded else
                 self._make_rect_sprite(ENEMY_WIDTH, ENEMY_HEIGHT, 0x8B4513))
            s.hidden = True
            self._enemy_sprites.append(s)
            self._sprite_group.append(s)

        # Coin pool
        self._coin_sprites = []
        for _ in range(20):
            s = (self._make_sheet_sprite(sl.coin_sheet, sl.coin_palette, 8, 14)
                 if sl.loaded else
                 self._make_rect_sprite(8, 14, 0xFCBC00))
            s.hidden = True
            self._coin_sprites.append(s)
            self._sprite_group.append(s)

        # Mario (always rendered; managed separately from the pools)
        self._mario_sprite = (
            self._make_sheet_sprite(
                sl.mario_sheet, sl.mario_palette, MARIO_WIDTH, MARIO_HEIGHT)
            if sl.loaded else
            self._make_rect_sprite(MARIO_WIDTH, MARIO_HEIGHT, 0xFF0000))
        self._sprite_group.append(self._mario_sprite)

        print(f"Sprite pools: {len(self._platform_sprites)} platforms, "
              f"{len(self._enemy_sprites)} enemies, {len(self._coin_sprites)} coins")

    # -------------------------------------------------------------------------
    # Public drawing API
    # -------------------------------------------------------------------------

    def draw(self, model):
        """Update all sprite positions from the current model state.

        Called every tick (~30 FPS).  Only sprites inside the camera
        window (plus a 64-pixel buffer on each side) are shown; the
        rest are hidden.  Sprite properties are only written when they
        actually change to minimise displayio refresh overhead.

        Parameters
        ----------
        model : MarioModel
            Current game state.  This method only reads from it.
        """
        cam_x     = model.camera.x
        vis_left  = cam_x - 64
        vis_right = cam_x + DISPLAY_WIDTH + 64

        # --- Platforms -------------------------------------------------------
        pi = 0
        for p in model.level.platforms:
            if (p.x + p.width > vis_left and p.x < vis_right and
                pi < len(self._platform_sprites)):
                sp = self._platform_sprites[pi]
                nx, ny = int(p.x - cam_x), int(p.y)
                if sp.x != nx: sp.x = nx
                if sp.y != ny: sp.y = ny
                if sp.hidden:  sp.hidden = False
                if self._sprites.loaded:
                    sp[0] = self._TILE_MAP.get(p.block_type, 0)
                pi += 1
        # Hide unused platform slots
        for i in range(pi, len(self._platform_sprites)):
            if not self._platform_sprites[i].hidden:
                self._platform_sprites[i].hidden = True

        # --- Coins -----------------------------------------------------------
        ci = 0
        for coin in model.level.coins:
            if (not coin.collected and
                coin.x + 8 > vis_left and coin.x < vis_right and
                ci < len(self._coin_sprites)):
                sp = self._coin_sprites[ci]
                nx, ny = int(coin.x - cam_x), int(coin.y)
                if sp.x != nx: sp.x = nx
                if sp.y != ny: sp.y = ny
                if sp.hidden:  sp.hidden = False
                ci += 1
        for i in range(ci, len(self._coin_sprites)):
            if not self._coin_sprites[i].hidden:
                self._coin_sprites[i].hidden = True

        # --- Enemies ---------------------------------------------------------
        ei = 0
        for enemy in model.level.enemies:
            if (enemy.alive and
                enemy.x + enemy.width > vis_left and enemy.x < vis_right and
                ei < len(self._enemy_sprites)):
                sp = self._enemy_sprites[ei]
                nx, ny = int(enemy.x - cam_x), int(enemy.y)
                if sp.x != nx: sp.x = nx
                if sp.y != ny: sp.y = ny
                if sp.hidden:  sp.hidden = False
                if self._sprites.loaded:
                    sp[0] = enemy.sprite_frame
                ei += 1
        for i in range(ei, len(self._enemy_sprites)):
            if not self._enemy_sprites[i].hidden:
                self._enemy_sprites[i].hidden = True

        # --- Mario (blink every 10 ticks while invincible) -------------------
        mario = model.mario
        if mario.invincible == 0 or mario.invincible % 10 < 5:
            nx, ny = int(mario.x - cam_x), int(mario.y)
            self._mario_sprite.x      = nx
            self._mario_sprite.y      = ny
            self._mario_sprite.hidden = False
            if self._sprites.loaded:
                if mario.sprite_frame != self._last_mario_frame:
                    self._mario_sprite[0]  = mario.sprite_frame
                    self._last_mario_frame = mario.sprite_frame
                facing = not mario.facing_right   # flip_x = True when facing left
                if facing != self._last_mario_flip:
                    self._mario_sprite.flip_x = facing
                    self._last_mario_flip     = facing
        else:
            self._mario_sprite.hidden = True

        # --- HUD -------------------------------------------------------------
        self._hud.update(model.score, model.coins, model.lives)

    # -------------------------------------------------------------------------
    # Audio
    # -------------------------------------------------------------------------

    def play_sfx(self, name: str):
        """Play a named sound effect (non-blocking)."""
        self._audio.play(name)

    def stop_audio(self):
        """Stop the current sound and release audio resources."""
        self._audio.stop()

    def is_audio_playing(self) -> bool:
        """True if audio is currently playing."""
        return self._audio.is_playing()

    # -------------------------------------------------------------------------
    # Overlay management
    # -------------------------------------------------------------------------

    def show_victory(self, score: int, coins: int):
        """Show the level-complete overlay and hide the HUD."""
        self._victory.show(score, coins)
        self._hud.hide()

    def show_game_over(self):
        """Show the game-over overlay and hide the HUD."""
        self._game_over.show()
        self._hud.hide()

    def hide_overlays(self):
        """Remove all overlays and restore the HUD (call on level reset)."""
        self._victory.hide()
        self._game_over.hide()
        self._hud.show()

    # -------------------------------------------------------------------------
    # NeoPixel feedback
    # -------------------------------------------------------------------------

    def update_neopixels(self, model, level_complete: bool = False):
        """Update the 5 NeoPixels to reflect current game state.

        Pixel mapping:
          0   : run indicator  -- amber while holding the run button
          1-3 : lives (green = still alive, off = lost that life)
          4   : jump indicator -- blue while Mario is in the air
        On level complete all pixels turn gold.
        """
        if self._px is None:
            return
        mario = model.mario
        if level_complete:
            self._px.fill(0xFFD700)   # gold: victory
        else:
            self._px[0] = 0xFFFF00 if mario.is_running    else 0x000000
            for i in range(min(model.lives, 3)):
                self._px[i + 1] = 0x00FF00  # green per remaining life
            for i in range(model.lives, 3):
                self._px[i + 1] = 0x000000  # off for lost lives
            self._px[4] = 0x0000FF if mario.jump_triggered else 0x000000
        self._px.show()

    def flash_neopixels_gameover(self):
        """Set all 5 NeoPixels to red on game over."""
        if self._px is not None:
            self._px.fill(0xFF0000)
            self._px.show()
