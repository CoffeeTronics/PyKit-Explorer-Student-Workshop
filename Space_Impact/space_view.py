# space_view.py - VIEW (MVC pattern)
#
# All visual and audio output for the Space Impact game.
# Reads model state to position sprites; never modifies game state.
#
# Constructor parameters (injected by the Controller):
#   display -- ST7789 display object (rotation / size already configured)
#   px      -- neopixel.NeoPixel strip (5 pixels, brightness pre-set)
#
# displayio layer structure (back to front):
#   main_group
#     +-- space background   (static black bitmap)
#     +-- _star_group        (30 star TileGrids -- parallax scrolling)
#     +-- _sprite_group      (bullets, enemies, power-ups, explosions, ship)
#     +-- _hud               (SCORE / LIVES / LEVEL / SPECIAL labels)
#     +-- _victory_screen    (level-complete / all-clear overlay)
#     +-- _gameover_screen   (game-over overlay)
#
# Public API (called by the Controller):
#   draw(model)                  -- reposition all sprites each tick
#   play_sfx(name)               -- trigger a WAV sound effect
#   stop_audio()                 -- stop current playback
#   is_audio_playing()           -- True while a sound is active
#   show_victory(score, level)   -- display level-complete overlay
#   show_all_clear(score)        -- display final victory overlay
#   show_game_over()             -- display game-over overlay
#   hide_overlays()              -- remove overlays, restore HUD
#   update_neopixels(model)      -- set 5 NeoPixels to reflect game state
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

from space_model import (
    DISPLAY_WIDTH, DISPLAY_HEIGHT,
    SHIP_WIDTH, SHIP_HEIGHT,
    BULLET_WIDTH, BULLET_HEIGHT,
    EBULLET_WIDTH, EBULLET_HEIGHT,
    ENEMY_WIDTH, ENEMY_HEIGHT,
    POWERUP_WIDTH, POWERUP_HEIGHT,
    NUM_STARS_FAST, NUM_STARS_SLOW,
    ET_SCOUT, ET_WEAVER, ET_DIVER, ET_BOSS,
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
        "shoot":        "/AudioFiles/si_shoot.wav",
        "explosion":    "/AudioFiles/si_explosion.wav",
        "powerup":      "/AudioFiles/si_powerup.wav",
        "hit":          "/AudioFiles/si_hit.wav",
        "boss_explode": "/AudioFiles/si_boss_explode.wav",
        "gameover":     "/AudioFiles/si_gameover.wav",
        "level_clear":  "/AudioFiles/si_level_clear.wav",
    }
    _MIN_INTERVAL = 0.08  # minimum seconds between plays (rate limiter)
    _REINIT_EVERY = 50    # re-create AudioOut every N plays

    def __init__(self):
        self.enabled    = False
        self._audio     = None
        self._file      = None
        self._wave      = None
        self._last_t    = 0.0
        self._count     = 0
        self._available = {}

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
        for name, path in self._SOUNDS.items():
            try:
                with open(path, "rb"):
                    pass
                self._available[name] = path
                print(f"  audio ok: {name}")
            except Exception:
                pass

    def play(self, sound_name):
        if not self.enabled or sound_name not in self._available:
            return
        import time
        now = time.monotonic()
        if now - self._last_t < self._MIN_INTERVAL:
            return
        try:
            self._cleanup()
            self._count += 1
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
        self._cleanup()

    def is_playing(self):
        if self.enabled and self._audio:
            try:
                return self._audio.playing
            except Exception:
                pass
        return False

    def _cleanup(self):
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
        self.loaded              = False
        self.ship_sheet          = None; self.ship_palette         = None
        self.enemy_sheet         = None; self.enemy_palette        = None
        self.bullet_sheet        = None; self.bullet_palette       = None
        self.enemy_bullet_sheet  = None; self.enemy_bullet_palette = None
        self.powerup_sheet       = None; self.powerup_palette      = None
        self.explosion_sheet     = None; self.explosion_palette    = None
        self._load()

    def _load(self):
        try:
            self.ship_sheet, self.ship_palette = adafruit_imageload.load(
                "/Sprites/ship_sprites.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.enemy_sheet, self.enemy_palette = adafruit_imageload.load(
                "/Sprites/enemy_sprites.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.bullet_sheet, self.bullet_palette = adafruit_imageload.load(
                "/Sprites/bullet_sprite.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.enemy_bullet_sheet, self.enemy_bullet_palette = adafruit_imageload.load(
                "/Sprites/enemy_bullet_sprite.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.powerup_sheet, self.powerup_palette = adafruit_imageload.load(
                "/Sprites/powerup_sprites.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.explosion_sheet, self.explosion_palette = adafruit_imageload.load(
                "/Sprites/explosion_sprites.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self.loaded = True
            print("Sprites loaded OK")
        except Exception as e:
            print(f"Sprite load failed: {e} -- using coloured rectangles")


# ===========================================================================
# HUD (private helper)
# ===========================================================================
class _HUD:
    """Score, lives, level, and special-ammo labels across the top."""
    def __init__(self, parent_group):
        self._group = displayio.Group()
        parent_group.append(self._group)

        self._score   = _label.Label(terminalio.FONT, text="SCORE:0",
                                     color=0xFFFFFF, x=5,   y=5)
        self._lives   = _label.Label(terminalio.FONT, text="HP:3",
                                     color=0x00FF00, x=90,  y=5)
        self._level   = _label.Label(terminalio.FONT, text="LV:1",
                                     color=0x00CCFF, x=135, y=5)
        self._special = _label.Label(terminalio.FONT, text="SP:3",
                                     color=0xCC00FF, x=185, y=5)
        for lbl in (self._score, self._lives, self._level, self._special):
            self._group.append(lbl)

        self._last_score   = -1
        self._last_lives   = -1
        self._last_level   = -1
        self._last_special = -1

    def update(self, score, lives, level, special):
        if score != self._last_score:
            self._score.text = f"SCORE:{score}"
            self._last_score = score
        if lives != self._last_lives:
            self._lives.text = f"HP:{lives}"
            self._last_lives = lives
        if level != self._last_level:
            self._level.text = f"LV:{level}"
            self._last_level = level
        if special != self._last_special:
            self._special.text = f"SP:{special}"
            self._last_special = special

    def show(self):
        self._group.hidden = False

    def hide(self):
        self._group.hidden = True


# ===========================================================================
# VictoryScreen (private helper)
# ===========================================================================
class _VictoryScreen:
    """Level-complete or all-clear overlay."""
    def __init__(self, parent_group):
        self._group = displayio.Group()
        parent_group.append(self._group)

        bg_bmp = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
        bg_pal = displayio.Palette(1); bg_pal[0] = 0x000020
        self._group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))

        self._title = _label.Label(
            terminalio.FONT, text="LEVEL COMPLETE!",
            color=0xFFD700, scale=2, x=20, y=35)
        self._group.append(self._title)

        self._score_lbl = _label.Label(
            terminalio.FONT, text="SCORE: 0",
            color=0xFFFFFF, scale=2, x=40, y=65)
        self._group.append(self._score_lbl)

        self._sub_lbl = _label.Label(
            terminalio.FONT, text="",
            color=0x00CCFF, scale=1, x=50, y=95)
        self._group.append(self._sub_lbl)

        self._group.hidden = True

    def show_level(self, score, level):
        self._title.text      = "LEVEL COMPLETE!"
        self._score_lbl.text  = f"SCORE: {score}"
        self._sub_lbl.text    = f"ENTERING LEVEL {level + 1}..."
        self._group.hidden    = False

    def show_all_clear(self, score):
        self._title.text      = "ALL CLEAR!"
        self._title.color     = 0x00FF00
        self._score_lbl.text  = f"FINAL: {score}"
        self._sub_lbl.text    = "CONGRATULATIONS!"
        self._group.hidden    = False

    def hide(self):
        self._group.hidden   = True
        self._title.color    = 0xFFD700


# ===========================================================================
# GameOverScreen (private helper)
# ===========================================================================
class _GameOverScreen:
    """Game-over overlay.  Tries BMP, falls back to text."""
    def __init__(self, parent_group):
        self._group = displayio.Group()
        parent_group.append(self._group)

        try:
            bmp, pal = adafruit_imageload.load(
                "/Sprites/Game_Over_SI.BMP",
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
# StartScreen (private helper)
# ===========================================================================
class _StartScreen:
    """Title / start menu overlay.

    Shows the game title, controls summary, and a blinking
    "PRESS BUTTON TO START" prompt.  Hidden once the game begins.
    """
    def __init__(self, parent_group):
        self._group = displayio.Group()
        parent_group.append(self._group)

        # Solid dark-blue background
        bg_bmp = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
        bg_pal = displayio.Palette(1); bg_pal[0] = 0x000018
        self._group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))

        # Decorative star dots (static)
        star_bmp = displayio.Bitmap(2, 1, 1)
        star_pal = displayio.Palette(1); star_pal[0] = 0x555566
        self._star_tgs = []
        _rng = 7919  # simple deterministic scatter
        for _ in range(25):
            _rng = (_rng * 1103515245 + 12345) & 0x7FFFFFFF
            sx = (_rng >> 16) % DISPLAY_WIDTH
            _rng = (_rng * 1103515245 + 12345) & 0x7FFFFFFF
            sy = (_rng >> 16) % DISPLAY_HEIGHT
            tg = displayio.TileGrid(star_bmp, pixel_shader=star_pal,
                                    x=sx, y=sy)
            self._group.append(tg)
            self._star_tgs.append(tg)

        # Title: "SPACE IMPACT"
        self._title = _label.Label(
            terminalio.FONT, text="SPACE IMPACT",
            color=0x00CCFF, scale=3,
            anchor_point=(0.5, 0.5),
            anchored_position=(120, 28))
        self._group.append(self._title)

        # Separator line
        line_bmp = displayio.Bitmap(160, 1, 1)
        line_pal = displayio.Palette(1); line_pal[0] = 0x0066AA
        self._group.append(displayio.TileGrid(
            line_bmp, pixel_shader=line_pal, x=40, y=46))

        # Controls info
        self._group.append(_label.Label(
            terminalio.FONT, text="TILT : MOVE SHIP",
            color=0x88AACC, scale=1,
            anchor_point=(0.5, 0.5),
            anchored_position=(120, 60)))
        self._group.append(_label.Label(
            terminalio.FONT, text="BTN  : FIRE",
            color=0x88AACC, scale=1,
            anchor_point=(0.5, 0.5),
            anchored_position=(120, 72)))
        self._group.append(_label.Label(
            terminalio.FONT, text="TOUCH: SPECIAL",
            color=0x88AACC, scale=1,
            anchor_point=(0.5, 0.5),
            anchored_position=(120, 84)))

        # "PRESS BUTTON TO START" prompt (blinks via show/hide)
        self._prompt = _label.Label(
            terminalio.FONT, text="PRESS BUTTON TO START",
            color=0xFFFF00, scale=1,
            anchor_point=(0.5, 0.5),
            anchored_position=(120, 108))
        self._group.append(self._prompt)

        # Bottom credit line
        self._group.append(_label.Label(
            terminalio.FONT, text="PyKit Explorer Edition",
            color=0x445566, scale=1,
            anchor_point=(0.5, 0.5),
            anchored_position=(120, 128)))

        self._blink_counter = 0
        self._group.hidden = True

    def show(self):
        self._group.hidden = False
        self._blink_counter = 0

    def hide(self):
        self._group.hidden = True

    def blink_prompt(self):
        """Call every frame to blink the start prompt (~1 Hz)."""
        self._blink_counter += 1
        if self._blink_counter >= 30:
            self._blink_counter = 0
        self._prompt.hidden = (self._blink_counter >= 15)


# ===========================================================================
# SpaceView -- public class used by the Controller
# ===========================================================================
class SpaceView:
    """All visual and audio output for the Space Impact game.

    Constructor parameters (injected by the Controller):
        display -- ST7789 display object (rotation/size already configured)
        px      -- neopixel.NeoPixel strip (5 pixels, brightness pre-set)
    """

    # Maps enemy_type to tile index in the enemy sprite sheet
    _ENEMY_TILE = {ET_SCOUT: 0, ET_WEAVER: 1, ET_DIVER: 2, ET_BOSS: 3}

    def __init__(self, display, px):
        self._display = display
        self._px      = px

        self._audio   = _AudioManager()
        self._sprites = _SpriteLoader()

        # --- Root displayio group ----------------------------------------
        self.main_group = displayio.Group()
        display.root_group = self.main_group

        # Static black space background
        bg_bmp = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
        bg_pal = displayio.Palette(1); bg_pal[0] = 0x000008
        self.main_group.append(
            displayio.TileGrid(bg_bmp, pixel_shader=bg_pal, x=0, y=0))

        # Star group (parallax background)
        self._star_group = displayio.Group()
        self.main_group.append(self._star_group)
        self._star_sprites = []
        self._build_star_pool()

        # Sprite group for all game entities
        self._sprite_group = displayio.Group()
        self.main_group.append(self._sprite_group)
        self._build_sprite_pools()

        # HUD and overlays (always on top)
        self._hud        = _HUD(self.main_group)
        self._victory    = _VictoryScreen(self.main_group)
        self._game_over  = _GameOverScreen(self.main_group)
        self._start_menu = _StartScreen(self.main_group)

        # Dirty-flag tracking for ship sprite
        self._last_ship_frame = -1

    # ---------------------------------------------------------------------
    # Star pool
    # ---------------------------------------------------------------------
    def _build_star_pool(self):
        total = NUM_STARS_FAST + NUM_STARS_SLOW
        # Stars are tiny 2x1 bitmaps -- bright for fast, dim for slow
        bright_bmp = displayio.Bitmap(2, 1, 1)
        bright_pal = displayio.Palette(1); bright_pal[0] = 0xCCCCCC
        dim_bmp    = displayio.Bitmap(2, 1, 1)
        dim_pal    = displayio.Palette(1); dim_pal[0] = 0x555566

        for i in range(total):
            if i < NUM_STARS_FAST:
                s = displayio.TileGrid(bright_bmp, pixel_shader=bright_pal,
                                       x=0, y=0)
            else:
                s = displayio.TileGrid(dim_bmp, pixel_shader=dim_pal,
                                       x=0, y=0)
            s.hidden = True
            self._star_sprites.append(s)
            self._star_group.append(s)

    # ---------------------------------------------------------------------
    # Sprite pool construction
    # ---------------------------------------------------------------------
    def _make_sheet_sprite(self, sheet, palette, tw, th):
        return displayio.TileGrid(
            sheet, pixel_shader=palette,
            width=1, height=1,
            tile_width=tw, tile_height=th,
            x=0, y=0)

    def _make_rect_sprite(self, w, h, color):
        bmp = displayio.Bitmap(w, h, 1)
        pal = displayio.Palette(1); pal[0] = color
        return displayio.TileGrid(bmp, pixel_shader=pal)

    def _build_sprite_pools(self):
        sl = self._sprites

        # Player bullets (8)
        self._bullet_sprites = []
        for _ in range(8):
            s = (self._make_sheet_sprite(
                     sl.bullet_sheet, sl.bullet_palette,
                     BULLET_WIDTH, BULLET_HEIGHT)
                 if sl.loaded else
                 self._make_rect_sprite(BULLET_WIDTH, BULLET_HEIGHT, 0x00FFFF))
            s.hidden = True
            self._bullet_sprites.append(s)
            self._sprite_group.append(s)

        # Enemy bullets (6)
        self._ebullet_sprites = []
        for _ in range(6):
            s = (self._make_sheet_sprite(
                     sl.enemy_bullet_sheet, sl.enemy_bullet_palette,
                     EBULLET_WIDTH, EBULLET_HEIGHT)
                 if sl.loaded else
                 self._make_rect_sprite(EBULLET_WIDTH, EBULLET_HEIGHT, 0xFF3333))
            s.hidden = True
            self._ebullet_sprites.append(s)
            self._sprite_group.append(s)

        # Enemies (12)
        self._enemy_sprites = []
        for _ in range(12):
            s = (self._make_sheet_sprite(
                     sl.enemy_sheet, sl.enemy_palette,
                     ENEMY_WIDTH, ENEMY_HEIGHT)
                 if sl.loaded else
                 self._make_rect_sprite(ENEMY_WIDTH, ENEMY_HEIGHT, 0xDD2222))
            s.hidden = True
            self._enemy_sprites.append(s)
            self._sprite_group.append(s)

        # Power-ups (3)
        self._powerup_sprites = []
        for _ in range(3):
            s = (self._make_sheet_sprite(
                     sl.powerup_sheet, sl.powerup_palette,
                     POWERUP_WIDTH, POWERUP_HEIGHT)
                 if sl.loaded else
                 self._make_rect_sprite(POWERUP_WIDTH, POWERUP_HEIGHT, 0x00FF00))
            s.hidden = True
            self._powerup_sprites.append(s)
            self._sprite_group.append(s)

        # Explosions (5)
        self._explosion_sprites = []
        for _ in range(5):
            s = (self._make_sheet_sprite(
                     sl.explosion_sheet, sl.explosion_palette, 16, 16)
                 if sl.loaded else
                 self._make_rect_sprite(16, 16, 0xFF6600))
            s.hidden = True
            self._explosion_sprites.append(s)
            self._sprite_group.append(s)

        # Player ship (1)
        self._ship_sprite = (
            self._make_sheet_sprite(
                sl.ship_sheet, sl.ship_palette,
                SHIP_WIDTH, SHIP_HEIGHT)
            if sl.loaded else
            self._make_rect_sprite(SHIP_WIDTH, SHIP_HEIGHT, 0x00BBFF))
        self._sprite_group.append(self._ship_sprite)

        pool_total = (len(self._bullet_sprites) + len(self._ebullet_sprites) +
                      len(self._enemy_sprites) + len(self._powerup_sprites) +
                      len(self._explosion_sprites) + 1)
        print(f"Sprite pools: {pool_total} game + "
              f"{len(self._star_sprites)} stars")

    # ---------------------------------------------------------------------
    # Public drawing API
    # ---------------------------------------------------------------------
    def draw(self, model):
        """Update all sprite positions from the current model state."""

        # --- Stars -------------------------------------------------------
        for i, star in enumerate(model.stars):
            if i < len(self._star_sprites):
                sp = self._star_sprites[i]
                nx, ny = int(star.x), int(star.y)
                if sp.x != nx: sp.x = nx
                if sp.y != ny: sp.y = ny
                if sp.hidden:  sp.hidden = False

        # --- Player bullets ----------------------------------------------
        bi = 0
        for b in model.bullets:
            if b.active and bi < len(self._bullet_sprites):
                sp = self._bullet_sprites[bi]
                nx, ny = int(b.x), int(b.y)
                if sp.x != nx: sp.x = nx
                if sp.y != ny: sp.y = ny
                if sp.hidden:  sp.hidden = False
                bi += 1
        for i in range(bi, len(self._bullet_sprites)):
            if not self._bullet_sprites[i].hidden:
                self._bullet_sprites[i].hidden = True

        # --- Enemy bullets -----------------------------------------------
        ei = 0
        for eb in model.enemy_bullets:
            if eb.active and ei < len(self._ebullet_sprites):
                sp = self._ebullet_sprites[ei]
                nx, ny = int(eb.x), int(eb.y)
                if sp.x != nx: sp.x = nx
                if sp.y != ny: sp.y = ny
                if sp.hidden:  sp.hidden = False
                ei += 1
        for i in range(ei, len(self._ebullet_sprites)):
            if not self._ebullet_sprites[i].hidden:
                self._ebullet_sprites[i].hidden = True

        # --- Enemies -----------------------------------------------------
        ni = 0
        for enemy in model.enemies:
            if enemy.alive and ni < len(self._enemy_sprites):
                sp = self._enemy_sprites[ni]
                nx, ny = int(enemy.x), int(enemy.y)
                if sp.x != nx: sp.x = nx
                if sp.y != ny: sp.y = ny
                if sp.hidden:  sp.hidden = False
                if self._sprites.loaded:
                    tile = self._ENEMY_TILE.get(enemy.enemy_type, 0)
                    if sp[0] != tile:
                        sp[0] = tile
                ni += 1
        for i in range(ni, len(self._enemy_sprites)):
            if not self._enemy_sprites[i].hidden:
                self._enemy_sprites[i].hidden = True

        # --- Power-ups ---------------------------------------------------
        pi = 0
        for pu in model.powerups:
            if pu.active and pi < len(self._powerup_sprites):
                sp = self._powerup_sprites[pi]
                nx, ny = int(pu.x), int(pu.y)
                if sp.x != nx: sp.x = nx
                if sp.y != ny: sp.y = ny
                if sp.hidden:  sp.hidden = False
                if self._sprites.loaded:
                    if sp[0] != pu.pu_type:
                        sp[0] = pu.pu_type
                pi += 1
        for i in range(pi, len(self._powerup_sprites)):
            if not self._powerup_sprites[i].hidden:
                self._powerup_sprites[i].hidden = True

        # --- Explosions --------------------------------------------------
        xi = 0
        for ex in model.explosions:
            if ex.active and xi < len(self._explosion_sprites):
                sp = self._explosion_sprites[xi]
                nx, ny = int(ex.x), int(ex.y)
                if sp.x != nx: sp.x = nx
                if sp.y != ny: sp.y = ny
                if sp.hidden:  sp.hidden = False
                if self._sprites.loaded:
                    if sp[0] != ex.frame:
                        sp[0] = ex.frame
                xi += 1
        for i in range(xi, len(self._explosion_sprites)):
            if not self._explosion_sprites[i].hidden:
                self._explosion_sprites[i].hidden = True

        # --- Player ship (blink while invincible) ------------------------
        ship = model.ship
        if ship.invincible == 0 or ship.invincible % 8 < 4:
            nx, ny = int(ship.x), int(ship.y)
            self._ship_sprite.x      = nx
            self._ship_sprite.y      = ny
            self._ship_sprite.hidden = False
            if self._sprites.loaded:
                if ship.sprite_frame != self._last_ship_frame:
                    self._ship_sprite[0]  = ship.sprite_frame
                    self._last_ship_frame = ship.sprite_frame
        else:
            self._ship_sprite.hidden = True

        # --- HUD ---------------------------------------------------------
        self._hud.update(model.score, model.lives,
                         model.level, model.ship.special_ammo)

    # ---------------------------------------------------------------------
    # Audio
    # ---------------------------------------------------------------------
    def play_sfx(self, name):
        self._audio.play(name)

    def stop_audio(self):
        self._audio.stop()

    def is_audio_playing(self):
        return self._audio.is_playing()

    # ---------------------------------------------------------------------
    # Overlay management
    # ---------------------------------------------------------------------
    def show_victory(self, score, level):
        self._victory.show_level(score, level)
        self._hud.hide()

    def show_all_clear(self, score):
        self._victory.show_all_clear(score)
        self._hud.hide()

    def show_game_over(self):
        self._game_over.show()
        self._hud.hide()

    def hide_overlays(self):
        self._victory.hide()
        self._game_over.hide()
        self._start_menu.hide()
        self._hud.show()

    # ---------------------------------------------------------------------
    # Start menu
    # ---------------------------------------------------------------------
    def show_start_menu(self):
        """Show the title / start menu overlay and hide everything else."""
        self._hud.hide()
        self._victory.hide()
        self._game_over.hide()
        self._start_menu.show()

    def hide_start_menu(self):
        """Hide the start menu and restore the HUD."""
        self._start_menu.hide()
        self._hud.show()

    def blink_start_prompt(self):
        """Call every frame while the start menu is visible."""
        self._start_menu.blink_prompt()

    # ---------------------------------------------------------------------
    # NeoPixel feedback
    # ---------------------------------------------------------------------
    def update_neopixels(self, model):
        """Update the 5 NeoPixels to reflect current game state.

        Pixel mapping:
          0   : shield (cyan) / special available (purple) / off
          1-3 : lives (green per life, off when lost)
          4   : firing flash (white when shooting, off otherwise)
        On level complete all pixels turn gold.
        """
        if self._px is None:
            return
        ship = model.ship

        if model.level_complete or model.all_clear:
            self._px.fill(0xFFD700)   # gold: victory
        else:
            # Pixel 0: shield / special indicator
            if ship.has_shield:
                self._px[0] = 0x00FFFF   # cyan
            elif ship.special_ammo > 0:
                self._px[0] = 0x800080   # purple
            else:
                self._px[0] = 0x000000

            # Pixels 1-3: lives
            for i in range(3):
                if i < model.lives:
                    self._px[i + 1] = 0x00FF00
                else:
                    self._px[i + 1] = 0x000000

            # Pixel 4: firing indicator
            self._px[4] = 0xFFFFFF if ship.firing else 0x000000

        self._px.show()

    def flash_neopixels_gameover(self):
        if self._px is not None:
            self._px.fill(0xFF0000)
            self._px.show()
