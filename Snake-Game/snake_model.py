# snake_model.py - MODEL (MVC pattern)
#
# The Model is the "brain" of the game.  It stores ALL game state and
# contains ALL game rules.  Crucially, it has ZERO knowledge of hardware:
# no display, no audio, no LEDs, no IMU.  This separation means:
#   - The game logic can be tested on a PC without any board attached.
#   - Swapping the display or input method requires NO changes here.
#
# What lives here:
#   - Snake body positions, current direction, food location
#   - Score and high-score (persisted to NVM flash memory)
#   - Collision detection and food placement
#   - AI autopilot logic for demo mode
#
# How it communicates with the Controller:
#   - The Controller calls step() once per game tick.
#   - step() returns an event string ("ate_food", "died", or None)
#     so the Controller knows which View methods to call.
#   - The Controller calls set_direction() when the player tilts the board.
#   - The Controller calls toggle_demo() when the touch pad is tapped.

import struct
import microcontroller

# Direction constants -- each is a (dx, dy) tuple used to move the snake
# one cell per tick.  (0,0) is the top-left corner of the grid.
UP    = (0, -1)   # y decreases going up
DOWN  = (0,  1)   # y increases going down
LEFT  = (-1, 0)   # x decreases going left
RIGHT = (1,  0)   # x increases going right

# Grid dimensions (in cells, not pixels -- the View handles scaling)
GRID_W = 24
GRID_H = 18

# NVM (Non-Volatile Memory) layout for persisting the high score across
# power cycles.  The first 4 bytes are a magic marker ("HSv1") so we can
# detect uninitialised NVM.  The next 2 bytes are the high score as an
# unsigned 16-bit integer (max 65535).
_NVM_MAGIC = b"HSv1"
_NVM_FMT   = "<4sH"                       # little-endian: 4-char + uint16
_NVM_SIZE  = struct.calcsize(_NVM_FMT)     # = 6 bytes


class SnakeModel:
    """Pure game state -- no hardware references of any kind.

    The Controller creates one instance at startup, then repeatedly:
      1. Calls set_direction() or toggle_demo() based on user input
      2. Calls step() to advance the game by one tick
      3. Reads the return value of step() to decide what to show

    Attributes (all public -- read by the View via the Controller):
        snake      -- list of (x, y) tuples; index 0 is the head
        direction  -- current movement direction (UP/DOWN/LEFT/RIGHT)
        food       -- (x, y) position of the current food pellet
        score      -- points scored this round (resets on death)
        high_score -- best score ever (persisted in NVM)
        demo_mode  -- True when the AI is playing automatically
    """

    def __init__(self):
        # Initialise all attributes to defaults
        self.snake     = []
        self.direction = RIGHT
        self.food      = (GRID_W // 3, GRID_H // 3)
        self.grow      = 0        # cells still to grow (after eating)
        self.score     = 0
        self.high_score = 0
        self.demo_mode = False

        # Load the persisted high score from NVM, then place the snake
        self._load_high_score()
        self.reset(reset_score=True)

    # =========================================================================
    # PUBLIC API -- called by the Controller
    # =========================================================================

    def reset(self, reset_score=True):
        """Reset the snake to its starting position in the centre of the grid.

        Parameters
        ----------
        reset_score : if True, reset the current score to 0.
                      Set to False after demo-mode deaths so the
                      AI score does not overwrite the player score.
        """
        # Build a 4-segment snake moving right from the centre
        self.snake = [(GRID_W // 2 + i, GRID_H // 2)
                      for i in range(1, -3, -1)]
        self.direction = RIGHT
        self.grow = 0
        if reset_score:
            self.score = 0

    def toggle_demo(self):
        """Flip between manual play and AI demo mode.

        Returns the new demo_mode value so the Controller can
        tell the View to update the mode LED colour.
        """
        self.demo_mode = not self.demo_mode
        return self.demo_mode

    def set_direction(self, new_dir):
        """Accept a new direction from the Controller (IMU tilt input).

        Rejects 180-degree reversals -- you cannot turn directly back
        on yourself (that would be instant death).
        """
        # Calculate the reverse of the current direction
        rev = (-self.direction[0], -self.direction[1])
        if new_dir != rev:
            self.direction = new_dir

    def step(self):
        """Advance the game by one tick -- the core game-loop method.

        This is called by the Controller every TICK_S seconds (0.12 s).
        It moves the snake one cell in the current direction and checks
        for collisions and food.

        Returns
        -------
        None         -- normal move, nothing special happened
        "ate_food"   -- snake ate the food pellet this tick
        "died"       -- snake hit a wall or its own body

        On "died" the Model does NOT reset itself -- it leaves that to
        the Controller, which first tells the View to show the game-over
        screen, then calls model.reset().
        """
        # In demo mode, let the AI choose the next direction before moving
        if self.demo_mode:
            self._ai_step()

        # Calculate the new head position
        dx, dy = self.direction
        nx = self.snake[0][0] + dx
        ny = self.snake[0][1] + dy

        # --- Collision detection ---
        # Wall collision: new head is outside the grid bounds
        if nx < 0 or ny < 0 or nx >= GRID_W or ny >= GRID_H:
            return "died"
        # Self collision: new head overlaps any existing body segment
        if (nx, ny) in self.snake:
            return "died"

        # --- Move the snake ---
        # Insert the new head at the front of the list
        self.snake.insert(0, (nx, ny))

        # --- Check if we ate the food ---
        event = None
        if (nx, ny) == self.food:
            # In manual mode, update score and persist high score
            if not self.demo_mode:
                self.score += 1
                if self.score > self.high_score:
                    self.high_score = self.score
                    self._save_high_score()
            # Queue 2 cells of growth (snake gets longer by 2)
            self.grow += 2
            # Place a new food pellet somewhere the snake is not
            self._place_food()
            event = "ate_food"

        # --- Grow or trim the tail ---
        # If we are still growing, keep the tail; otherwise remove it
        # so the snake appears to slither forward
        if self.grow > 0:
            self.grow -= 1
        else:
            self.snake.pop()

        return event

    # =========================================================================
    # FOOD PLACEMENT (private)
    # =========================================================================

    def _place_food(self):
        """Find an empty cell for the next food pellet.

        Uses a deterministic scan starting from an offset of the current
        food position.  This avoids the cost of random number generation
        on CircuitPython while still giving varied-looking placement.
        """
        start = ((self.food[0] + 7) % GRID_W, (self.food[1] + 5) % GRID_H)
        snake_set = set(self.snake)   # O(1) lookup instead of O(n)
        for dy in range(GRID_H):
            for dx in range(GRID_W):
                x = (start[0] + dx) % GRID_W
                y = (start[1] + dy) % GRID_H
                if (x, y) not in snake_set:
                    self.food = (x, y)
                    return

    # =========================================================================
    # AI AUTOPILOT -- demo mode (private)
    # =========================================================================

    def _ai_step(self):
        """Choose the best safe direction that moves towards the food.

        Strategy (greedy, not perfect):
          1. Build a list of directions sorted by preference towards food
          2. Pick the first one that does not cause an immediate collision
          3. If none work, keep current direction if safe
          4. Last resort: pick any non-reversing in-bounds direction
        """
        head = self.snake[0]
        body_set = set(self.snake)
        # The reverse direction -- we must never go backwards
        rev = (-self.direction[0], -self.direction[1])

        # Try directions in order of preference (closest to food first)
        for d in self._neighbors_preferring_food(head, self.food):
            if d == rev:
                continue
            nx, ny = head[0] + d[0], head[1] + d[1]
            if not self._would_collide((nx, ny), body_set):
                self.direction = d
                return

        # Fallback: keep current direction if it is safe
        nx, ny = head[0] + self.direction[0], head[1] + self.direction[1]
        if not self._would_collide((nx, ny), body_set):
            return

        # Last resort: any non-reversing direction that stays in bounds
        for d in (RIGHT, DOWN, LEFT, UP):
            if d == rev:
                continue
            nx, ny = head[0] + d[0], head[1] + d[1]
            if 0 <= nx < GRID_W and 0 <= ny < GRID_H:
                self.direction = d
                return

    @staticmethod
    def _neighbors_preferring_food(head, target):
        """Return all 4 directions sorted by how well they approach target.

        If the food is more to the right than up/down, horizontal moves
        are tried first.  Deduplicates and appends all 4 cardinals so
        every direction is present exactly once.
        """
        hx, hy = head
        fx, fy = target
        # Sign of the vector from head to food
        dx = 1 if fx > hx else (-1 if fx < hx else 0)
        dy = 1 if fy > hy else (-1 if fy < hy else 0)
        # Prefer the axis with the larger distance to food
        if abs(fx - hx) >= abs(fy - hy):
            ordered = [(dx, 0), (0, dy), (-dx, 0), (0, -dy)]
        else:
            ordered = [(0, dy), (dx, 0), (0, -dy), (-dx, 0)]
        # Deduplicate while preserving order
        out = []
        for d in ordered + [RIGHT, LEFT, DOWN, UP]:
            if d not in out:
                out.append(d)
        return out

    @staticmethod
    def _would_collide(pos, body_set):
        """Return True if pos is out of bounds or overlaps the snake body."""
        x, y = pos
        return x < 0 or y < 0 or x >= GRID_W or y >= GRID_H or pos in body_set

    # =========================================================================
    # NVM HIGH-SCORE PERSISTENCE (private)
    # =========================================================================

    @staticmethod
    def _nvm_available():
        """Check whether this board has Non-Volatile Memory support."""
        return getattr(microcontroller, "nvm", None) is not None

    def _load_high_score(self):
        """Read the high score from NVM on startup.

        If NVM is uninitialised (no magic marker) or unavailable,
        defaults to 0.
        """
        if not self._nvm_available() or len(microcontroller.nvm) < _NVM_SIZE:
            self.high_score = 0
            return
        raw = bytes(microcontroller.nvm[0:_NVM_SIZE])
        try:
            magic, hs = struct.unpack(_NVM_FMT, raw)
            self.high_score = hs if magic == _NVM_MAGIC else 0
        except Exception:
            self.high_score = 0

    def _save_high_score(self):
        """Write the current high score to NVM so it survives power cycles."""
        if not self._nvm_available() or len(microcontroller.nvm) < _NVM_SIZE:
            return
        try:
            microcontroller.nvm[0:_NVM_SIZE] = struct.pack(
                _NVM_FMT, _NVM_MAGIC, min(self.high_score, 65535)
            )
        except Exception:
            pass