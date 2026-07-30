# mario_model.py - MODEL (MVC pattern)
#
# Pure game state and rules -- zero hardware knowledge.
# The Controller passes an InputState each tick; the Model returns
# a list of event strings so the Controller can trigger View effects.
#
# What lives here:
#   - Game constants (gravity, speeds, dimensions)
#   - InputState -- decoupled snapshot of controls (tilt, jump, run)
#   - Platform, Coin, Enemy, Mario data classes + physics
#   - Level -- builds and owns all platforms, enemies, and coins
#   - Camera -- smooth-follow scrolling offset
#   - MarioModel -- top-level game state, drives one tick via update()
#
# Events returned by MarioModel.update():
#   "jumped"         -- Mario left the ground this tick
#   "coin"           -- Mario collected a coin
#   "stomp"          -- Mario stomped an enemy
#   "enemy_hit"      -- Mario was hurt by an enemy (lost a life)
#   "fall_death"     -- Mario fell off the bottom of the level
#   "gameover"       -- Lives reached 0
#   "level_complete" -- Mario reached the end flag
#   "level_reset"    -- Victory timer expired; level restarted

import gc

# ---------------------------------------------------------------------------
# Physics and level constants
# ---------------------------------------------------------------------------
GRAVITY       = 0.6
JUMP_STRENGTH = -10
MOVE_SPEED    = 2.5
RUN_SPEED     = 4.5
GROUND_Y      = 105   # y-coordinate of the ground surface (pixels)
LEVEL_END_X   = 2075  # Mario must reach this x to complete the level

# Entity dimensions in pixels
MARIO_WIDTH  = 16
MARIO_HEIGHT = 16
ENEMY_WIDTH  = 16
ENEMY_HEIGHT = 16
BLOCK_SIZE   = 16

# Display size -- Camera needs these to clamp scrolling
DISPLAY_WIDTH  = 240
DISPLAY_HEIGHT = 135


# ---------------------------------------------------------------------------
# InputState
# ---------------------------------------------------------------------------
class InputState:
    """Decoupled snapshot of player controls for one game tick.

    The Controller reads hardware (IMU, buttons, touch) and fills this
    object, then passes it to MarioModel.update().  The Model never
    touches hardware directly -- this is what keeps it testable on a PC.

    Attributes
    ----------
    tilt_value : float in [-1.0, 1.0]
        Negative = left, positive = right.  Magnitude controls speed.
    jump : bool
        True on the tick a jump press is registered (edge-triggered,
        held for a few frames by the Controller to catch quick taps).
    run : bool
        True while the run button is held (capacitive touch).
    """
    __slots__ = ("tilt_value", "jump", "run")

    def __init__(self):
        self.tilt_value = 0.0
        self.jump       = False
        self.run        = False


# ---------------------------------------------------------------------------
# AABB collision helper
# ---------------------------------------------------------------------------
def check_collision(x1, y1, w1, h1, x2, y2, w2, h2):
    """Return True if the two axis-aligned rectangles overlap."""
    return (x1 < x2 + w2 and x1 + w1 > x2 and
            y1 < y2 + h2 and y1 + h1 > y2)


# ---------------------------------------------------------------------------
# Level entities
# ---------------------------------------------------------------------------
class Platform:
    """A static rectangular tile in the level.

    Attributes
    ----------
    x, y       : top-left position in world coordinates (pixels)
    width      : width in pixels
    height     : height in pixels
    block_type : "brick", "question", or "pipe"
                 Used by the View to select the correct tile sprite.
    """
    def __init__(self, x, y, width, height, block_type="brick"):
        self.x          = x
        self.y          = y
        self.width      = width
        self.height     = height
        self.block_type = block_type


class Coin:
    """A collectible coin at a fixed world position.

    Attributes
    ----------
    x, y      : world position (pixels)
    collected : set to True when Mario touches this coin
    """
    def __init__(self, x, y):
        self.x         = x
        self.y         = y
        self.collected = False


class Enemy:
    """A Goomba enemy that walks back and forth and falls with gravity.

    The Model drives all physics.  The View reads sprite_frame (0 or 1)
    to select the walk animation frame.
    """
    _NEARBY = 100   # only check platforms within this many pixels (optimisation)

    def __init__(self, x, y):
        self.x             = x
        self.y             = y
        self.width         = ENEMY_WIDTH
        self.height        = ENEMY_HEIGHT
        self.vel_x         = -1.0   # starts walking left
        self.vel_y         = 0.0
        self.alive         = True
        self.on_ground     = False
        self.sprite_frame  = 0      # 0 or 1: walk animation frame read by View
        self.frame_counter = 0      # ticks until next animation frame flip

    def update(self, platforms):
        """Advance enemy physics by one tick.

        Returns True if the enemy fell below the level (caller removes it).
        """
        if not self.alive:
            return False

        self.x     += self.vel_x
        self.vel_y += GRAVITY
        self.y     += self.vel_y

        nearby = self._NEARBY
        self.on_ground = False

        # Landing / ground check
        for p in platforms:
            if abs(p.x - self.x) > nearby:
                continue
            if (self.x + self.width > p.x and self.x < p.x + p.width and
                self.vel_y >= 0 and
                self.y + self.height >= p.y and
                self.y + self.height <= p.y + p.height + 5):
                self.y        = p.y - self.height
                self.vel_y    = 0
                self.on_ground = True
                break

        # Wall bounce: only trigger when the enemy's midpoint is inside the
        # platform's vertical range.  The old condition (enemy bottom below
        # platform bottom) fired on every elevated platform the enemy walked
        # beneath, causing rapid 1-2 frame oscillation.
        enemy_mid_y = self.y + self.height // 2
        for p in platforms:
            if abs(p.x - self.x) > nearby:
                continue
            if (self.x + self.width > p.x and self.x < p.x + p.width and
                p.y < enemy_mid_y < p.y + p.height):
                if self.vel_x > 0:
                    self.x = p.x - self.width
                else:
                    self.x = p.x + p.width
                self.vel_x *= -1
                break

        # Walk animation (flip every 15 ticks)
        self.frame_counter += 1
        if self.frame_counter >= 15:
            self.sprite_frame  = 1 - self.sprite_frame
            self.frame_counter = 0

        # Fell out of the level?
        return self.y > DISPLAY_HEIGHT + 50

    def stomp(self):
        """Mark enemy as dead after Mario lands on top of it."""
        self.alive = False


class Mario:
    """Mario entity -- movement, jumping, platform collisions.

    Reads an InputState each tick; never touches hardware directly.

    Attributes read by the View
    ---------------------------
    x, y           : world position (top-left corner, pixels)
    sprite_frame   : 0 = stand, 1 = walk, 2 = jump
    facing_right   : True when looking right (View flips sprite when False)
    invincible     : countdown in ticks after being hit by an enemy
    jump_triggered : True on the tick Mario leaves the ground (NeoPixel hint)
    is_running     : True while the run button is held (NeoPixel hint)
    """
    def __init__(self, x, y):
        self.x              = x
        self.y              = y
        self.vel_x          = 0.0
        self.vel_y          = 0.0
        self.on_ground      = False
        self.facing_right   = True
        self.width          = MARIO_WIDTH
        self.height         = MARIO_HEIGHT
        self.is_running     = False
        self.invincible     = 0
        self.sprite_frame   = 0
        self.anim_counter   = 0
        self.jump_triggered = False

    def update(self, input_state, platforms):
        """Apply one tick of physics driven by an InputState.

        Parameters
        ----------
        input_state : InputState
            Current player controls from the Controller.
        platforms   : list of Platform
            All platforms in the current Level.
        """
        prev_y = self.y

        # Decrement invincibility countdown
        if self.invincible > 0:
            self.invincible -= 1

        # Horizontal movement
        if input_state.tilt_value != 0:
            speed             = RUN_SPEED if input_state.run else MOVE_SPEED
            self.vel_x        = input_state.tilt_value * speed
            self.facing_right = input_state.tilt_value > 0
            # Walking animation while on the ground
            if self.on_ground:
                self.anim_counter += 1
                if self.anim_counter > 5:
                    self.sprite_frame = 1 if self.sprite_frame == 0 else 0
                    self.anim_counter = 0
        else:
            # Friction / deceleration
            self.vel_x *= 0.8
            if abs(self.vel_x) < 0.1:
                self.vel_x = 0
            self.sprite_frame = 0  # standing still

        # Jump (only from the ground)
        if input_state.jump and self.on_ground:
            self.vel_y          = JUMP_STRENGTH
            self.jump_triggered = True
            self.on_ground      = False

        # Jump sprite overrides walk sprite while airborne
        if not self.on_ground:
            self.sprite_frame = 2

        # Gravity
        if not self.on_ground:
            self.vel_y += GRAVITY
            if self.vel_y > 10:
                self.vel_y = 10  # terminal velocity

        # Apply velocity
        self.x += self.vel_x
        self.y += self.vel_y

        # Platform collision (only check nearby platforms for speed)
        self.on_ground = False
        for p in platforms:
            if abs(p.x - self.x) > 150 and abs(p.y - self.y) > 150:
                continue
            if self._resolve_platform(p, prev_y):
                break

        # Ground floor
        if self.y >= GROUND_Y:
            self.y              = GROUND_Y
            self.vel_y          = 0
            self.on_ground      = True
            self.jump_triggered = False

    def _resolve_platform(self, p, prev_y):
        """Resolve collision with one platform.  Returns True if resolved."""
        if not (self.x + self.width > p.x and self.x < p.x + p.width and
                self.y + self.height > p.y and self.y < p.y + p.height):
            return False

        # Land on top of platform
        if prev_y + self.height <= p.y and self.vel_y > 0:
            self.y              = p.y - self.height
            self.vel_y          = 0
            self.on_ground      = True
            self.jump_triggered = False
            return True

        # Hit underside of platform (head bump)
        if prev_y >= p.y + p.height and self.vel_y < 0:
            self.y     = p.y + p.height
            self.vel_y = 0
            return True

        return False


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------
class Level:
    """Builds and owns all platforms, enemies, and coins for world 1-1.

    The entire world is 2200 pixels wide.  All positions use world
    coordinates; the Camera offset is applied by the View during draw().
    """
    def __init__(self):
        self.platforms = []
        self.enemies   = []
        self.coins     = []
        self._build()

    def _build(self):
        """Populate all level objects."""
        # Ground row
        for i in range(0, 2200, BLOCK_SIZE):
            self.platforms.append(Platform(i, GROUND_Y + 15, BLOCK_SIZE, BLOCK_SIZE))

        # Question blocks
        for x in [200, 250, 300]:
            self.platforms.append(Platform(x, 70, BLOCK_SIZE, BLOCK_SIZE, "question"))

        # Brick platform
        for x in range(400, 550, BLOCK_SIZE):
            self.platforms.append(Platform(x, 80, BLOCK_SIZE, BLOCK_SIZE, "brick"))

        # High platform
        for x in range(700, 800, BLOCK_SIZE):
            self.platforms.append(Platform(x, 60, BLOCK_SIZE, BLOCK_SIZE))

        # Pipe 1
        self.platforms.append(Platform(900, 90, BLOCK_SIZE, BLOCK_SIZE * 3, "pipe"))

        # Mid platforms
        for x in range(1100, 1250, BLOCK_SIZE):
            self.platforms.append(Platform(x, 70, BLOCK_SIZE, BLOCK_SIZE))

        # Staircase
        for x in range(1400, 1550, BLOCK_SIZE):
            y_off = ((x - 1400) // BLOCK_SIZE) * BLOCK_SIZE
            self.platforms.append(Platform(x, GROUND_Y - y_off, BLOCK_SIZE, BLOCK_SIZE))

        # Late bricks
        for x in range(1700, 1900, BLOCK_SIZE):
            self.platforms.append(Platform(x, 50, BLOCK_SIZE, BLOCK_SIZE, "brick"))

        # End pipe / flag area
        self.platforms.append(Platform(2050, 70, BLOCK_SIZE, BLOCK_SIZE * 2, "pipe"))

        # Enemies
        for x in [150, 350, 600, 950, 1200, 1500, 1800]:
            self.enemies.append(Enemy(x, GROUND_Y))

        # Coins (positioned above platforms so they are reachable)
        for x in [225, 275, 475, 525]:
            self.coins.append(Coin(x, 50))
        self.coins.append(Coin(750,  30))
        self.coins.append(Coin(1175, 50))
        self.coins.append(Coin(1450, 30))
        self.coins.append(Coin(1750, 30))


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------
class Camera:
    """Smooth-follow side-scrolling camera.

    Attributes
    ----------
    x : float
        Current left-edge offset in pixels.  The View subtracts this
        from a world x position to get the screen x position.
    """
    _SMOOTHING = 0.2
    _WORLD_W   = 2200   # total level width in pixels

    def __init__(self):
        self.x       = 0.0
        self._target = 0.0

    def update(self, mario_x):
        """Advance the camera toward Mario's position."""
        self._target = mario_x - DISPLAY_WIDTH // 3
        self._target = max(0, min(self._target, self._WORLD_W - DISPLAY_WIDTH))
        self.x      += (self._target - self.x) * self._SMOOTHING


# ---------------------------------------------------------------------------
# MarioModel
# ---------------------------------------------------------------------------
class MarioModel:
    """Top-level game state.  Drives one tick of logic via update().

    The Controller calls update(input_state) every frame and receives a
    list of event strings.  It routes those events to View methods so
    the Model never needs to know about display, audio, or LEDs.

    Public attributes read by the View (via the Controller):
        mario          -- Mario instance
        level          -- Level instance (platforms, enemies, coins)
        camera         -- Camera instance
        score          -- int, current score
        coins          -- int, coins collected this run
        lives          -- int, lives remaining
        game_over      -- bool, True when lives == 0
        level_complete -- bool, True after Mario reaches LEVEL_END_X
    """

    def __init__(self):
        gc.collect()
        self._init_state()

    def _init_state(self):
        """Allocate all game objects and reset counters."""
        self.level          = Level()
        self.mario          = Mario(40, GROUND_Y)
        self.camera         = Camera()
        self.score          = 0
        self.coins          = 0
        self.lives          = 3
        self.game_over      = False
        self.level_complete = False
        self._victory_timer = 0   # countdown (ticks) before level restart

    def reset(self):
        """Full reset: new Level, Mario at start, all counters zeroed.

        Called by the Controller after the game-over hold screen,
        or by the Model itself when the victory timer expires.
        """
        gc.collect()
        self._init_state()

    def update(self, input_state):
        """Advance the game by one tick.

        Parameters
        ----------
        input_state : InputState
            Current player controls filled in by the Controller.

        Returns
        -------
        list of str
            Zero or more event strings (see module docstring for values).
        """
        events = []

        if self.game_over:
            return events

        # Victory countdown -- pause all game updates during victory screen
        if self.level_complete and self._victory_timer > 0:
            self._victory_timer -= 1
            if self._victory_timer == 0:
                self.reset()
                events.append("level_reset")
            return events

        # --- Mario physics ---------------------------------------------------
        mario_was_on_ground  = self.mario.on_ground
        self.mario.is_running = input_state.run
        self.mario.update(input_state, self.level.platforms)

        # Detect the jump leaving the ground this tick
        if mario_was_on_ground and not self.mario.on_ground and self.mario.vel_y < 0:
            events.append("jumped")

        # --- Camera ----------------------------------------------------------
        self.camera.update(self.mario.x)

        # --- Enemy updates ---------------------------------------------------
        for enemy in self.level.enemies[:]:   # copy so we can remove during iteration
            fell = enemy.update(self.level.platforms)
            if fell:
                self.level.enemies.remove(enemy)
                continue

            if enemy.alive and self.mario.invincible == 0:
                if check_collision(
                    self.mario.x, self.mario.y, self.mario.width, self.mario.height,
                    enemy.x,      enemy.y,      enemy.width,      enemy.height,
                ):
                    if self.mario.vel_y > 0 and self.mario.y < enemy.y:
                        # Mario stomped the enemy
                        enemy.stomp()
                        self.score       += 100
                        self.mario.vel_y  = -6   # small bounce
                        events.append("stomp")
                    else:
                        # Enemy hit Mario
                        self.lives          -= 1
                        self.mario.invincible = 120   # ~4 seconds of invincibility
                        events.append("enemy_hit")
                        if self.lives <= 0:
                            self.game_over = True
                            events.append("gameover")

        # --- Coin collection -------------------------------------------------
        for coin in self.level.coins:
            if not coin.collected:
                if check_collision(
                    self.mario.x, self.mario.y, self.mario.width, self.mario.height,
                    coin.x, coin.y, 8, 14,
                ):
                    coin.collected  = True
                    self.coins     += 1
                    self.score     += 200
                    events.append("coin")

        # --- Level completion ------------------------------------------------
        if not self.level_complete and self.mario.x >= LEVEL_END_X:
            self.level_complete  = True
            self._victory_timer  = 180   # hold for 6 s at 30 FPS
            events.append("level_complete")

        # --- Fall death ------------------------------------------------------
        if self.mario.y > DISPLAY_HEIGHT:
            self.lives -= 1
            events.append("fall_death")
            if self.lives <= 0:
                self.game_over = True
                events.append("gameover")
            else:
                # Respawn at start
                self.mario.x          = 40
                self.mario.y          = GROUND_Y
                self.mario.invincible = 120

        return events
