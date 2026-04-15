# space_model.py - MODEL (MVC pattern)
#
# Pure game state and rules -- zero hardware knowledge.
# The Controller passes an InputState each tick; the Model returns
# a list of event strings so the Controller can trigger View effects.
#
# What lives here:
#   - Game constants (speeds, dimensions, scoring)
#   - InputState -- decoupled snapshot of controls (tilt_x, tilt_y, fire, special)
#   - Ship, Bullet, EnemyBullet, Enemy, Boss, PowerUp, Explosion, Star
#   - WaveManager -- enemy spawn patterns and level progression
#   - SpaceModel -- top-level game state, drives one tick via update()
#
# Events returned by SpaceModel.update():
#   "fired"             -- player shot a bullet
#   "special_fired"     -- player used special weapon
#   "enemy_destroyed"   -- enemy killed
#   "boss_hit"          -- boss took damage but survived
#   "boss_destroyed"    -- boss killed
#   "player_hit"        -- ship took damage (lost a life)
#   "shield_hit"        -- shield absorbed a hit
#   "powerup_collected" -- power-up grabbed
#   "level_complete"    -- all waves + boss cleared
#   "level_reset"       -- victory timer expired, next level starts
#   "gameover"          -- lives reached 0
#   "all_clear"         -- beat all 3 levels (final victory)

import gc
import math

# ---------------------------------------------------------------------------
# Display and physics constants
# ---------------------------------------------------------------------------
DISPLAY_WIDTH  = 240
DISPLAY_HEIGHT = 135

# Ship constraints -- can move within the left portion of the screen
SHIP_MIN_X     = 5
SHIP_MAX_X     = 90     # left ~40% of 240
SHIP_MIN_Y     = 12     # below HUD
SHIP_MAX_Y     = 119    # above bottom edge
SHIP_WIDTH     = 16
SHIP_HEIGHT    = 16
# Hitbox is slightly smaller than visual for forgiving collisions
SHIP_HIT_W     = 10
SHIP_HIT_H     = 8
SHIP_HIT_OX    = 3      # offset from ship.x
SHIP_HIT_OY    = 4      # offset from ship.y

SHIP_SPEED     = 2.5    # pixels per tick at full tilt

# Bullets
BULLET_SPEED   = 5      # player bullet speed (rightward)
BULLET_WIDTH   = 6
BULLET_HEIGHT  = 4
SPECIAL_SPEED  = 4
SPECIAL_WIDTH  = 10
SPECIAL_HEIGHT = 6
FIRE_COOLDOWN  = 6      # ticks between normal shots (~5/sec at 30 FPS)
RAPID_COOLDOWN = 3      # ticks between shots during rapid fire

# Enemy bullets
EBULLET_SPEED  = 3
EBULLET_WIDTH  = 4
EBULLET_HEIGHT = 4

# Enemies
ENEMY_WIDTH    = 16
ENEMY_HEIGHT   = 16

# Power-ups
POWERUP_WIDTH  = 8
POWERUP_HEIGHT = 8
POWERUP_SPEED  = 1      # drifts left slowly

# Scoring
SCORE_SCOUT    = 100
SCORE_WEAVER   = 200
SCORE_DIVER    = 300
SCORE_BOSS     = 1000
SCORE_POWERUP  = 50
SCORE_LEVEL    = 500

# Invincibility after being hit
INVINCIBLE_TICKS  = 90   # ~3 seconds at 30 FPS
RAPID_FIRE_TICKS  = 300  # ~10 seconds

# Power-up types
PU_SHIELD     = 0
PU_RAPID      = 1
PU_LIFE       = 2

# Enemy types
ET_SCOUT  = 0
ET_WEAVER = 1
ET_DIVER  = 2
ET_BOSS   = 3

# Star layers
NUM_STARS_FAST = 12
NUM_STARS_SLOW = 18
STAR_SPEED_FAST = 3
STAR_SPEED_SLOW = 1


# ---------------------------------------------------------------------------
# InputState
# ---------------------------------------------------------------------------
class InputState:
    """Decoupled snapshot of player controls for one game tick.

    Attributes
    ----------
    tilt_x : float in [-1.0, 1.0]
        Negative = left, positive = right.
    tilt_y : float in [-1.0, 1.0]
        Negative = up, positive = down.
    fire : bool
        True while the fire button (D3) is held.
    special : bool
        True on the tick the special weapon button (CAP1) is pressed.
    """
    __slots__ = ("tilt_x", "tilt_y", "fire", "special")

    def __init__(self):
        self.tilt_x  = 0.0
        self.tilt_y  = 0.0
        self.fire    = False
        self.special = False


# ---------------------------------------------------------------------------
# AABB collision
# ---------------------------------------------------------------------------
def _collides(x1, y1, w1, h1, x2, y2, w2, h2):
    """Return True if two axis-aligned rectangles overlap."""
    return (x1 < x2 + w2 and x1 + w1 > x2 and
            y1 < y2 + h2 and y1 + h1 > y2)


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------
class Ship:
    """Player spaceship."""
    def __init__(self):
        self.x             = 30.0
        self.y             = 60.0
        self.vel_x         = 0.0
        self.vel_y         = 0.0
        self.invincible    = 0       # countdown ticks
        self.has_shield    = False
        self.rapid_fire    = 0       # countdown ticks
        self.special_ammo  = 3       # per level
        self.sprite_frame  = 0       # 0=neutral, 1=bank-up, 2=bank-down
        self.fire_cooldown = 0       # ticks until next shot allowed
        self.firing        = False   # True on ticks a bullet was fired

    def reset_for_level(self):
        self.x            = 30.0
        self.y            = 60.0
        self.vel_x        = 0.0
        self.vel_y        = 0.0
        self.invincible   = 0
        self.has_shield   = False
        self.rapid_fire   = 0
        self.special_ammo = 3
        self.sprite_frame = 0
        self.fire_cooldown = 0
        self.firing       = False


class Bullet:
    """Player projectile."""
    __slots__ = ("x", "y", "vel_x", "active", "is_special", "width", "height", "damage")

    def __init__(self):
        self.x          = 0.0
        self.y          = 0.0
        self.vel_x      = 0.0
        self.active     = False
        self.is_special = False
        self.width      = BULLET_WIDTH
        self.height     = BULLET_HEIGHT
        self.damage     = 1


class EnemyBullet:
    """Projectile fired by enemies / bosses."""
    __slots__ = ("x", "y", "vel_x", "vel_y", "active")

    def __init__(self):
        self.x      = 0.0
        self.y      = 0.0
        self.vel_x  = 0.0
        self.vel_y  = 0.0
        self.active = False


class Enemy:
    """Generic enemy.  Behaviour varies by enemy_type."""

    def __init__(self, x, y, enemy_type):
        self.x             = float(x)
        self.y             = float(y)
        self.enemy_type    = enemy_type
        self.alive         = True
        self.width         = ENEMY_WIDTH
        self.height        = ENEMY_HEIGHT
        self.sprite_frame  = 0
        self.frame_counter = 0
        self._spawn_y      = float(y)  # for sine wave reference
        self._tick         = 0          # lifetime in ticks
        self._fire_timer   = 0          # ticks until next shot

        if enemy_type == ET_SCOUT:
            self.vel_x  = -2.0
            self.vel_y  = 0.0
            self.hp     = 1
            self.points = SCORE_SCOUT
        elif enemy_type == ET_WEAVER:
            self.vel_x  = -1.5
            self.vel_y  = 0.0   # computed from sine in update
            self.hp     = 1
            self.points = SCORE_WEAVER
        elif enemy_type == ET_DIVER:
            self.vel_x  = -1.8
            self.vel_y  = 0.0
            self.hp     = 2
            self.points = SCORE_DIVER
        else:  # ET_BOSS
            self.vel_x  = -0.5
            self.vel_y  = 0.0
            self.hp     = 5
            self.points = SCORE_BOSS
            self.width  = 24
            self.height = 24

    def update(self, ship_y):
        """Advance one tick.  Returns True if off-screen (remove)."""
        self._tick += 1
        self.frame_counter += 1
        if self.frame_counter >= 15:
            self.sprite_frame  = 1 - self.sprite_frame
            self.frame_counter = 0

        if self.enemy_type == ET_WEAVER:
            # Sine wave: amplitude 25 px, period ~90 ticks
            self.y = self._spawn_y + 25.0 * math.sin(self._tick * 0.07)

        elif self.enemy_type == ET_DIVER:
            # Track player Y with limited turn rate
            dy = ship_y - self.y
            if abs(dy) > 2:
                self.vel_y = 1.5 if dy > 0 else -1.5
            else:
                self.vel_y = 0.0
            self.y += self.vel_y
            # Clamp to screen
            if self.y < SHIP_MIN_Y:
                self.y = float(SHIP_MIN_Y)
            elif self.y > SHIP_MAX_Y:
                self.y = float(SHIP_MAX_Y)

        elif self.enemy_type == ET_BOSS:
            # Boss oscillates vertically
            self.y = self._spawn_y + 20.0 * math.sin(self._tick * 0.03)
            # Boss stops advancing once it reaches its patrol x
            if self.x <= 180:
                self.vel_x = 0.0

        self.x += self.vel_x
        if self.enemy_type != ET_WEAVER and self.enemy_type != ET_DIVER:
            self.y += self.vel_y

        return self.x < -self.width - 10

    def should_fire(self, level):
        """Return True if this enemy should fire this tick."""
        if self.enemy_type == ET_BOSS:
            interval = max(40, 80 - level * 15)
        elif self.enemy_type == ET_DIVER:
            interval = max(60, 120 - level * 20)
        else:
            return False  # scouts and weavers don't shoot
        self._fire_timer += 1
        if self._fire_timer >= interval:
            self._fire_timer = 0
            return True
        return False

    def hit(self, damage):
        """Apply damage. Returns True if destroyed."""
        self.hp -= damage
        if self.hp <= 0:
            self.alive = False
            return True
        return False


class PowerUp:
    """Collectible power-up item."""
    __slots__ = ("x", "y", "pu_type", "active")

    def __init__(self, x, y, pu_type):
        self.x       = float(x)
        self.y       = float(y)
        self.pu_type = pu_type
        self.active  = True

    def update(self):
        self.x -= POWERUP_SPEED
        if self.x < -POWERUP_WIDTH:
            self.active = False


class Explosion:
    """Short-lived visual explosion marker."""
    __slots__ = ("x", "y", "frame", "timer", "active")

    def __init__(self, x, y):
        self.x      = float(x)
        self.y      = float(y)
        self.frame  = 0
        self.timer  = 0
        self.active = True

    def update(self):
        self.timer += 1
        if self.timer >= 5:
            self.timer = 0
            self.frame += 1
            if self.frame >= 3:
                self.active = False


class Star:
    """Background parallax star."""
    __slots__ = ("x", "y", "speed")

    def __init__(self, x, y, speed):
        self.x     = float(x)
        self.y     = float(y)
        self.speed = speed

    def update(self):
        self.x -= self.speed
        if self.x < -2:
            self.x = float(DISPLAY_WIDTH + 1)
            # Re-randomise Y to keep it interesting
            self.y = float(_pseudo_rand_y())


# Simple pseudo-random for star Y repositioning (no `random` module in CP)
_rand_state = 12345

def _pseudo_rand_y():
    global _rand_state
    _rand_state = (_rand_state * 1103515245 + 12345) & 0x7FFFFFFF
    return (_rand_state >> 16) % (DISPLAY_HEIGHT - 4) + 2

def _pseudo_rand_range(lo, hi):
    global _rand_state
    _rand_state = (_rand_state * 1103515245 + 12345) & 0x7FFFFFFF
    return lo + ((_rand_state >> 16) % (hi - lo + 1))


# ---------------------------------------------------------------------------
# Wave definitions
# ---------------------------------------------------------------------------
# Each wave is a list of (delay_ticks, enemy_type, y_position) tuples.
# delay_ticks is how many ticks after the previous spawn in the same wave.
# All enemies spawn from the right edge (x = DISPLAY_WIDTH + 10).

def _make_waves(level):
    """Generate wave list for the given level (1-3)."""
    waves = []

    if level == 1:
        # Level 1: Asteroid Belt -- scouts only, gentle pace
        for w in range(8):
            wave = []
            count = 2 + (w // 3)   # 2-4 scouts per wave
            for i in range(count):
                y = 20 + (i * 30) % 100
                wave.append((i * 18, ET_SCOUT, y))
            waves.append(wave)

    elif level == 2:
        # Level 2: Enemy Fleet -- scouts + weavers, some shooting enemies
        for w in range(10):
            wave = []
            count = 3 + (w // 4)
            for i in range(count):
                y = 15 + (i * 28) % 105
                etype = ET_WEAVER if (i + w) % 3 == 0 else ET_SCOUT
                wave.append((i * 15, etype, y))
            waves.append(wave)

    else:
        # Level 3: Command Ship -- all types, dense
        for w in range(12):
            wave = []
            count = 3 + (w // 3)
            for i in range(count):
                y = 15 + (i * 25) % 105
                if w >= 8 and i % 3 == 0:
                    etype = ET_DIVER
                elif (i + w) % 3 == 0:
                    etype = ET_WEAVER
                else:
                    etype = ET_SCOUT
                wave.append((i * 12, etype, y))
            waves.append(wave)

    return waves


def _get_boss_hp(level):
    """Boss hit points per level."""
    return [5, 8, 12][min(level - 1, 2)]


# ---------------------------------------------------------------------------
# WaveManager
# ---------------------------------------------------------------------------
class WaveManager:
    """Manages enemy wave spawning and boss triggers."""

    # Ticks between waves
    _WAVE_GAP = 90  # ~3 seconds

    def __init__(self, level):
        self.level       = level
        self.waves       = _make_waves(level)
        self.wave_idx    = 0      # current wave index
        self.spawn_idx   = 0      # index within current wave
        self.wave_timer  = 0      # ticks since wave started
        self.gap_timer   = 0      # ticks in gap between waves
        self.in_gap      = False  # True while waiting between waves
        self.boss_active = False
        self.all_done    = False  # True when boss is defeated

    def update(self, enemies):
        """Spawn enemies as needed.  Returns a list of new Enemy objects."""
        new_enemies = []

        if self.all_done or self.boss_active:
            return new_enemies

        if self.in_gap:
            self.gap_timer += 1
            if self.gap_timer >= self._WAVE_GAP:
                self.in_gap = False
                self.wave_timer = 0
                self.spawn_idx  = 0
            return new_enemies

        if self.wave_idx >= len(self.waves):
            # All waves done -- spawn boss
            self.boss_active = True
            boss_y = DISPLAY_HEIGHT // 2 - 12
            boss = Enemy(DISPLAY_WIDTH + 10, boss_y, ET_BOSS)
            boss.hp = _get_boss_hp(self.level)
            new_enemies.append(boss)
            return new_enemies

        # Spawn enemies from current wave
        wave = self.waves[self.wave_idx]
        while self.spawn_idx < len(wave):
            delay, etype, y = wave[self.spawn_idx]
            if self.wave_timer >= delay:
                e = Enemy(DISPLAY_WIDTH + 10, y, etype)
                new_enemies.append(e)
                self.spawn_idx += 1
            else:
                break

        self.wave_timer += 1

        # Check if current wave is fully spawned
        if self.spawn_idx >= len(wave):
            # Check if all enemies from this wave have left the screen or died
            # For simplicity, move to next wave after a gap
            self.wave_idx += 1
            self.in_gap    = True
            self.gap_timer = 0

        return new_enemies


# ---------------------------------------------------------------------------
# SpaceModel
# ---------------------------------------------------------------------------
class SpaceModel:
    """Top-level game state.  Drives one tick of logic via update().

    The Controller calls update(input_state) every frame and receives a
    list of event strings.  It routes those events to View methods so
    the Model never needs to know about display, audio, or LEDs.

    Public attributes read by the View (via the Controller):
        ship           -- Ship instance
        enemies        -- list of Enemy
        bullets        -- list of Bullet (pre-allocated pool)
        enemy_bullets  -- list of EnemyBullet (pre-allocated pool)
        powerups       -- list of PowerUp
        explosions     -- list of Explosion
        stars          -- list of Star
        score          -- int
        lives          -- int
        level          -- int (1-3)
        game_over      -- bool
        level_complete -- bool
        all_clear      -- bool (beat all 3 levels)
    """

    _MAX_BULLETS       = 8
    _MAX_ENEMY_BULLETS = 6
    _MAX_EXPLOSIONS    = 5
    _MAX_POWERUPS      = 3
    _MAX_ENEMIES       = 12

    def __init__(self):
        gc.collect()
        self._init_state()

    def _init_state(self):
        """Allocate all game objects and reset counters."""
        self.ship    = Ship()
        self.enemies = []
        self.score   = 0
        self.lives   = 3
        self.level   = 1
        self.game_over      = False
        self.level_complete = False
        self.all_clear      = False
        self._victory_timer = 0

        # Pre-allocate bullet pools
        self.bullets = []
        for _ in range(self._MAX_BULLETS):
            self.bullets.append(Bullet())

        self.enemy_bullets = []
        for _ in range(self._MAX_ENEMY_BULLETS):
            self.enemy_bullets.append(EnemyBullet())

        self.explosions = []
        self.powerups   = []

        # Stars (background)
        self.stars = []
        for i in range(NUM_STARS_FAST):
            x = _pseudo_rand_range(0, DISPLAY_WIDTH)
            y = _pseudo_rand_range(2, DISPLAY_HEIGHT - 4)
            self.stars.append(Star(x, y, STAR_SPEED_FAST))
        for i in range(NUM_STARS_SLOW):
            x = _pseudo_rand_range(0, DISPLAY_WIDTH)
            y = _pseudo_rand_range(2, DISPLAY_HEIGHT - 4)
            self.stars.append(Star(x, y, STAR_SPEED_SLOW))

        # Wave manager
        self._waves = WaveManager(self.level)

    def reset(self):
        """Full reset: level 1, score 0, all objects cleared."""
        gc.collect()
        self._init_state()

    def start_level(self, level):
        """Start a specific level, preserving score and lives."""
        self.level          = level
        self.level_complete = False
        self._victory_timer = 0
        self.ship.reset_for_level()
        self.enemies.clear()
        self.powerups.clear()
        self.explosions.clear()
        for b in self.bullets:
            b.active = False
        for eb in self.enemy_bullets:
            eb.active = False
        self._waves = WaveManager(level)

    def update(self, inp):
        """Advance the game by one tick.

        Parameters
        ----------
        inp : InputState
            Current player controls.

        Returns
        -------
        list of str
            Zero or more event strings.
        """
        events = []

        if self.game_over:
            return events

        if self.all_clear:
            # Hold victory screen
            if self._victory_timer > 0:
                self._victory_timer -= 1
            return events

        # Level complete countdown
        if self.level_complete:
            self._victory_timer -= 1
            if self._victory_timer <= 0:
                if self.level >= 3:
                    self.all_clear = True
                    self._victory_timer = 180
                    events.append("all_clear")
                else:
                    self.start_level(self.level + 1)
                    events.append("level_reset")
            return events

        # --- Ship movement ---------------------------------------------------
        ship = self.ship

        if ship.invincible > 0:
            ship.invincible -= 1
        if ship.rapid_fire > 0:
            ship.rapid_fire -= 1

        # Apply tilt to velocity
        ship.vel_x = inp.tilt_x * SHIP_SPEED
        ship.vel_y = inp.tilt_y * SHIP_SPEED

        ship.x += ship.vel_x
        ship.y += ship.vel_y

        # Clamp to bounds
        if ship.x < SHIP_MIN_X:
            ship.x = float(SHIP_MIN_X)
        elif ship.x > SHIP_MAX_X:
            ship.x = float(SHIP_MAX_X)
        if ship.y < SHIP_MIN_Y:
            ship.y = float(SHIP_MIN_Y)
        elif ship.y > SHIP_MAX_Y:
            ship.y = float(SHIP_MAX_Y)

        # Sprite frame: bank up/down based on vertical tilt
        if inp.tilt_y < -0.3:
            ship.sprite_frame = 1   # banking up
        elif inp.tilt_y > 0.3:
            ship.sprite_frame = 2   # banking down
        else:
            ship.sprite_frame = 0   # neutral

        # --- Player firing ---------------------------------------------------
        ship.firing = False
        if ship.fire_cooldown > 0:
            ship.fire_cooldown -= 1

        if inp.fire and ship.fire_cooldown <= 0:
            # Find an inactive bullet
            for b in self.bullets:
                if not b.active:
                    b.x          = ship.x + SHIP_WIDTH
                    b.y          = ship.y + SHIP_HEIGHT // 2 - BULLET_HEIGHT // 2
                    b.vel_x      = BULLET_SPEED
                    b.active     = True
                    b.is_special = False
                    b.width      = BULLET_WIDTH
                    b.height     = BULLET_HEIGHT
                    b.damage     = 1
                    ship.fire_cooldown = RAPID_COOLDOWN if ship.rapid_fire > 0 else FIRE_COOLDOWN
                    ship.firing = True
                    events.append("fired")
                    break

        # Special weapon
        if inp.special and ship.special_ammo > 0:
            for b in self.bullets:
                if not b.active:
                    b.x          = ship.x + SHIP_WIDTH
                    b.y          = ship.y + SHIP_HEIGHT // 2 - SPECIAL_HEIGHT // 2
                    b.vel_x      = SPECIAL_SPEED
                    b.active     = True
                    b.is_special = True
                    b.width      = SPECIAL_WIDTH
                    b.height     = SPECIAL_HEIGHT
                    b.damage     = 3
                    ship.special_ammo -= 1
                    events.append("special_fired")
                    break

        # --- Update bullets --------------------------------------------------
        for b in self.bullets:
            if b.active:
                b.x += b.vel_x
                if b.x > DISPLAY_WIDTH + 10:
                    b.active = False

        # --- Update enemy bullets --------------------------------------------
        for eb in self.enemy_bullets:
            if eb.active:
                eb.x += eb.vel_x
                eb.y += eb.vel_y
                if (eb.x < -10 or eb.x > DISPLAY_WIDTH + 10 or
                    eb.y < -10 or eb.y > DISPLAY_HEIGHT + 10):
                    eb.active = False

        # --- Spawn new enemies -----------------------------------------------
        new_enemies = self._waves.update(self.enemies)
        for e in new_enemies:
            if len(self.enemies) < self._MAX_ENEMIES:
                self.enemies.append(e)

        # --- Update enemies --------------------------------------------------
        for enemy in self.enemies[:]:
            off_screen = enemy.update(ship.y)
            if off_screen:
                self.enemies.remove(enemy)
                continue

            if not enemy.alive:
                continue

            # Enemy firing
            if enemy.should_fire(self.level):
                for eb in self.enemy_bullets:
                    if not eb.active:
                        eb.x = enemy.x
                        eb.y = enemy.y + enemy.height // 2 - EBULLET_HEIGHT // 2
                        if enemy.enemy_type == ET_BOSS:
                            # Boss fires spread pattern
                            eb.vel_x = -EBULLET_SPEED
                            eb.vel_y = 0.0
                        else:
                            # Aimed at player
                            dx = ship.x - enemy.x
                            dy = ship.y - enemy.y
                            # Normalise direction
                            dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
                            eb.vel_x = (dx / dist) * EBULLET_SPEED
                            eb.vel_y = (dy / dist) * EBULLET_SPEED
                        eb.active = True
                        break

                # Boss also fires spread bullets (up and down)
                if enemy.enemy_type == ET_BOSS:
                    spread_count = 0
                    for eb in self.enemy_bullets:
                        if not eb.active and spread_count < 2:
                            eb.x     = enemy.x
                            eb.y     = enemy.y + enemy.height // 2
                            eb.vel_x = -EBULLET_SPEED
                            eb.vel_y = 1.5 if spread_count == 0 else -1.5
                            eb.active = True
                            spread_count += 1

        # --- Bullet-enemy collisions -----------------------------------------
        for b in self.bullets:
            if not b.active:
                continue
            for enemy in self.enemies:
                if not enemy.alive:
                    continue
                if _collides(b.x, b.y, b.width, b.height,
                             enemy.x, enemy.y, enemy.width, enemy.height):
                    b.active = False
                    destroyed = enemy.hit(b.damage)
                    if destroyed:
                        self.score += enemy.points
                        self._spawn_explosion(enemy.x, enemy.y)
                        if enemy.enemy_type == ET_BOSS:
                            events.append("boss_destroyed")
                            self._waves.all_done = True
                            # Big explosion for boss
                            self._spawn_explosion(enemy.x + 8, enemy.y - 5)
                            self._spawn_explosion(enemy.x - 5, enemy.y + 8)
                        else:
                            events.append("enemy_destroyed")
                            # Maybe drop a power-up (~20% chance)
                            if _pseudo_rand_range(1, 100) <= 20:
                                pu_type = _pseudo_rand_range(0, 2)
                                if len(self.powerups) < self._MAX_POWERUPS:
                                    self.powerups.append(
                                        PowerUp(enemy.x, enemy.y, pu_type))
                    else:
                        if enemy.enemy_type == ET_BOSS:
                            events.append("boss_hit")
                    break  # one bullet hits one enemy

        # --- Remove dead enemies ---------------------------------------------
        self.enemies = [e for e in self.enemies if e.alive]

        # --- Enemy bullet-ship collision -------------------------------------
        if ship.invincible == 0:
            shx = ship.x + SHIP_HIT_OX
            shy = ship.y + SHIP_HIT_OY
            for eb in self.enemy_bullets:
                if not eb.active:
                    continue
                if _collides(shx, shy, SHIP_HIT_W, SHIP_HIT_H,
                             eb.x, eb.y, EBULLET_WIDTH, EBULLET_HEIGHT):
                    eb.active = False
                    self._apply_hit(events)
                    break

        # --- Enemy-ship collision --------------------------------------------
        if ship.invincible == 0:
            shx = ship.x + SHIP_HIT_OX
            shy = ship.y + SHIP_HIT_OY
            for enemy in self.enemies:
                if not enemy.alive:
                    continue
                if _collides(shx, shy, SHIP_HIT_W, SHIP_HIT_H,
                             enemy.x, enemy.y, enemy.width, enemy.height):
                    self._apply_hit(events)
                    break

        # --- Update power-ups ------------------------------------------------
        for pu in self.powerups[:]:
            pu.update()
            if not pu.active:
                self.powerups.remove(pu)
                continue
            if _collides(ship.x, ship.y, SHIP_WIDTH, SHIP_HEIGHT,
                         pu.x, pu.y, POWERUP_WIDTH, POWERUP_HEIGHT):
                pu.active = False
                self.score += SCORE_POWERUP
                if pu.pu_type == PU_SHIELD:
                    ship.has_shield = True
                elif pu.pu_type == PU_RAPID:
                    ship.rapid_fire = RAPID_FIRE_TICKS
                elif pu.pu_type == PU_LIFE:
                    if self.lives < 5:
                        self.lives += 1
                events.append("powerup_collected")
        self.powerups = [pu for pu in self.powerups if pu.active]

        # --- Update explosions -----------------------------------------------
        for ex in self.explosions[:]:
            ex.update()
            if not ex.active:
                self.explosions.remove(ex)
        # Cap explosion count
        while len(self.explosions) > self._MAX_EXPLOSIONS:
            self.explosions.pop(0)

        # --- Update stars (background) ---------------------------------------
        for star in self.stars:
            star.update()

        # --- Check level completion ------------------------------------------
        if self._waves.all_done and len(self.enemies) == 0:
            if not self.level_complete:
                self.level_complete = True
                self.score += SCORE_LEVEL
                self._victory_timer = 150   # ~5 seconds
                events.append("level_complete")

        return events

    # -----------------------------------------------------------------------
    # Private helpers
    # -----------------------------------------------------------------------

    def _apply_hit(self, events):
        """Handle the ship being hit by an enemy or bullet."""
        ship = self.ship
        if ship.has_shield:
            ship.has_shield = False
            events.append("shield_hit")
        else:
            self.lives -= 1
            ship.invincible = INVINCIBLE_TICKS
            self._spawn_explosion(ship.x, ship.y)
            events.append("player_hit")
            if self.lives <= 0:
                self.game_over = True
                events.append("gameover")

    def _spawn_explosion(self, x, y):
        """Create an explosion at the given position."""
        if len(self.explosions) < self._MAX_EXPLOSIONS:
            self.explosions.append(Explosion(x, y))
