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

from games.space_impact.model import (
    DISPLAY_WIDTH, DISPLAY_HEIGHT,
    SHIP_WIDTH, SHIP_HEIGHT,
    BULLET_WIDTH, BULLET_HEIGHT,
    EBULLET_WIDTH, EBULLET_HEIGHT,
    ENEMY_WIDTH, ENEMY_HEIGHT,
    POWERUP_WIDTH, POWERUP_HEIGHT,
    NUM_STARS_FAST, NUM_STARS_SLOW,
    ET_SCOUT, ET_WEAVER, ET_DIVER, ET_BOSS,
)

# Sound effect paths for preloading (reduced to 3 to save memory)
_SOUND_PATHS = {
    "shoot":        "/AudioFiles/si_shoot.wav",
    "explosion":    "/AudioFiles/si_explosion.wav",
    "gameover":     "/AudioFiles/gameover_man.wav",
}

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

    def __init__(self, display, px, audio=None):
        self._display = display
        self._px      = px
        self._audio = audio
        self._game_initialized = False

        # --- Root displayio group ----------------------------------------
        self.main_group = displayio.Group()
        display.root_group = self.main_group

        # Load splash screen FIRST before any heavy allocations
        gc.collect()
        self._splash_group = displayio.Group()
        self.main_group.append(self._splash_group)

        try:
            bmp, pal = adafruit_imageload.load(
                "/Sprites/SI_splash.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self._splash_group.append(
                displayio.TileGrid(bmp, pixel_shader=pal, x=0, y=0))
            print("SI splash image loaded")
        except Exception as e:
            print(f"SI splash load failed: {e}")
            bg_bmp = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
            bg_pal = displayio.Palette(1); bg_pal[0] = 0x000018
            self._splash_group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
            self._splash_group.append(_label.Label(
                terminalio.FONT, text="SPACE IMPACT",
                color=0x00CCFF, scale=3,
                anchor_point=(0.5, 0.5),
                anchored_position=(120, 50)))

        # Blinking prompt on splash
        self._splash_prompt = _label.Label(
            terminalio.FONT, text="PRESS BUTTON TO START",
            color=0xFFFF00, scale=1,
            anchor_point=(0.5, 0.5),
            anchored_position=(120, 108))
        self._splash_group.append(self._splash_prompt)
        self._blink_counter = 0

    def init_game_graphics(self):
        """Initialize heavy game graphics after splash is dismissed."""
        if self._game_initialized:
            return

        # Remove splash screen and free memory
        while len(self._splash_group):
            self._splash_group.pop()
        self.main_group.remove(self._splash_group)
        self._splash_group = None
        self._splash_prompt = None
        gc.collect()
        print(f"After splash release RAM: {gc.mem_free()}")

        # Now load game resources
        self._preload_sounds()
        self._sprites = _SpriteLoader()

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
        self._game_over_group = None  # Loaded lazily in show_game_over

        # Dirty-flag tracking for ship sprite
        self._last_ship_frame = -1

        self._game_initialized = True
        gc.collect()
        print(f"Game graphics initialized RAM: {gc.mem_free()}")

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
        gc.collect()

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
        gc.collect()

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
        gc.collect()

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
        gc.collect()

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
        gc.collect()

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
        gc.collect()

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

    def _release_all_for_gameover(self):
        """Release everything possible to free memory for game over screen."""
        # Release splash screen if still around
        if hasattr(self, '_splash_group') and self._splash_group is not None:
            try:
                while len(self._splash_group):
                    self._splash_group.pop()
                self.main_group.remove(self._splash_group)
            except (ValueError, AttributeError):
                pass
            self._splash_group = None

        # Remove all sprites from the sprite group
        if self._sprite_group is not None:
            while len(self._sprite_group):
                self._sprite_group.pop()
            try:
                self.main_group.remove(self._sprite_group)
            except ValueError:
                pass
            self._sprite_group = None

        # Remove star sprites
        if self._star_group is not None:
            while len(self._star_group):
                self._star_group.pop()
            try:
                self.main_group.remove(self._star_group)
            except ValueError:
                pass
            self._star_group = None

        # Clear the sprite lists
        self._bullet_sprites = None
        self._ebullet_sprites = None
        self._enemy_sprites = None
        self._powerup_sprites = None
        self._explosion_sprites = None
        self._star_sprites = None
        self._ship_sprite = None

        # Release the sprite sheet loader
        self._sprites = None

        # Don't unload audio - gameover sound needs to keep playing

        # Remove HUD from display
        if hasattr(self, '_hud') and self._hud is not None:
            try:
                self._hud._group.hidden = True
                self.main_group.remove(self._hud._group)
            except (ValueError, AttributeError):
                pass
            self._hud = None

        # Remove Victory screen from display
        if hasattr(self, '_victory') and self._victory is not None:
            try:
                self._victory._group.hidden = True
                self.main_group.remove(self._victory._group)
            except (ValueError, AttributeError):
                pass
            self._victory = None

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
    def _preload_sounds(self):
        """Preload all sound effects using the shared audio API."""
        if self._audio is None:
            print("SpaceView: No audio object provided")
            return
        print(f"SpaceView: Preloading {len(_SOUND_PATHS)} sounds...")
        for name, path in _SOUND_PATHS.items():
            try:
                gc.collect()
                self._audio.preload_wav(name, path)
                print(f"  Preloaded: {name}")
            except Exception as e:
                print(f"  Failed to preload {name}: {e}")

    def play_sfx(self, name):
        if self._audio:
            result = self._audio.play_preloaded(name)
            if not result:
                print(f"SpaceView: play_sfx({name}) failed")

    def stop_audio(self):
        if self._audio:
            self._audio.stop()

    def is_audio_playing(self):
        if self._audio:
            return self._audio.is_playing
        return False

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
        """Show the game-over overlay with a completely fresh display root."""
        # Release everything and create a completely new display root
        # This avoids memory fragmentation issues
        self._release_all_for_gameover()

        # Clear the old main_group completely
        while len(self.main_group):
            self.main_group.pop()
        self.main_group = None

        gc.collect()
        gc.collect()
        print(f"After full release RAM: {gc.mem_free()}")

        # Create a completely fresh display root
        self._game_over_group = displayio.Group()
        self._display.root_group = self._game_over_group

        try:
            bmp, pal = adafruit_imageload.load(
                "/Sprites/Game_Over_SI.bmp",
                bitmap=displayio.Bitmap, palette=displayio.Palette)
            self._game_over_group.append(
                displayio.TileGrid(bmp, pixel_shader=pal, x=0, y=0))
            print("SI Game Over image loaded")
        except Exception as e:
            print(f"SI Game Over load failed: {e}")
            bg_bmp = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
            bg_pal = displayio.Palette(1); bg_pal[0] = 0x000000
            self._game_over_group.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
            self._game_over_group.append(_label.Label(
                terminalio.FONT, text="GAME OVER",
                color=0xFF0000, scale=3,
                x=40, y=DISPLAY_HEIGHT // 2))

    def hide_game_over(self):
        """Remove game over overlay and free memory."""
        if self._game_over_group is not None:
            self.main_group.remove(self._game_over_group)
            self._game_over_group = None
            gc.collect()

    def hide_overlays(self):
        if self._game_initialized:
            self._victory.hide()
            self.hide_game_over()
            self._hud.show()

    # ---------------------------------------------------------------------
    # Start menu (splash screen)
    # ---------------------------------------------------------------------
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
