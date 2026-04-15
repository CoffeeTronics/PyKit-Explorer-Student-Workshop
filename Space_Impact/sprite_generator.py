"""
Space Impact Sprite Generator for CircuitPython
Creates indexed BMP files suitable for displayio / adafruit_imageload.

Run on your host computer with Python 3, then copy the generated .bmp
files into the /Sprites/ folder on your CircuitPython board.

Requirements:
    pip install pillow

Generated files:
    ship_sprites.bmp         48x16  (3 frames of 16x16: neutral, bank-up, bank-down)
    enemy_sprites.bmp        64x16  (4 types of 16x16: scout, weaver, diver, boss-piece)
    bullet_sprite.bmp         6x4   (player bullet)
    enemy_bullet_sprite.bmp   4x4   (enemy bullet)
    powerup_sprites.bmp      24x8   (3 types of 8x8: shield, rapid-fire, extra-life)
    explosion_sprites.bmp    48x16  (3 frames of 16x16)
    Game_Over.bmp           240x135 (full-screen game-over splash)
"""

from PIL import Image, ImageDraw, ImageFont
import os

# Output directory -- sprites land next to this script
_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Sprites")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _make_indexed(width, height, palette_rgb):
    """Create a P-mode (indexed) image with the given palette.

    Parameters
    ----------
    palette_rgb : list of (r, g, b) tuples -- up to 16 entries.
    """
    img = Image.new("P", (width, height))
    flat = []
    for r, g, b in palette_rgb:
        flat.extend([r, g, b])
    # Pad palette to 256 entries (required by BMP)
    flat.extend([0] * (768 - len(flat)))
    img.putpalette(flat)
    return img, ImageDraw.Draw(img)


# ---------------------------------------------------------------------------
# Player ship  (48x16 -- 3 frames of 16x16)
# ---------------------------------------------------------------------------
def create_ship_sprites():
    palette = [
        (0,   0,   0),    # 0: black (transparent background)
        (0,   180, 255),  # 1: cyan (hull)
        (0,   100, 200),  # 2: dark blue (hull shadow)
        (255, 80,  0),    # 3: orange (engine flame)
        (255, 200, 0),    # 4: yellow (engine core / cockpit)
        (200, 200, 200),  # 5: light grey (wing tips)
        (100, 100, 100),  # 6: dark grey (detail)
    ]
    img, d = _make_indexed(48, 16, palette)

    def _draw_ship(xo, flame_dy):
        """Draw one ship frame at x-offset *xo*.
        flame_dy shifts the engine flame vertically to suggest banking."""
        # Main hull (pointed nose on the right)
        d.polygon([(xo+14, 7), (xo+14, 8), (xo+6, 4), (xo+6, 11),
                    (xo+14, 8)], fill=1)
        # Fuselage rectangle
        d.rectangle([xo+2, 5, xo+10, 10], fill=1)
        # Cockpit (nose cone)
        d.rectangle([xo+11, 6, xo+14, 9], fill=2)
        d.rectangle([xo+12, 7, xo+13, 8], fill=4)  # canopy
        # Top wing
        d.polygon([(xo+4, 5), (xo+8, 5), (xo+8, 2), (xo+5, 2)], fill=2)
        d.point((xo+7, 2), fill=5)
        # Bottom wing
        d.polygon([(xo+4, 10), (xo+8, 10), (xo+8, 13), (xo+5, 13)], fill=2)
        d.point((xo+7, 13), fill=5)
        # Engine exhaust
        ey = 7 + flame_dy
        d.rectangle([xo+0, ey, xo+2, ey+1], fill=3)
        d.point((xo+1, ey), fill=4)

    _draw_ship(0,  0)    # Frame 0: neutral
    _draw_ship(16, -1)   # Frame 1: banking up
    _draw_ship(32,  1)   # Frame 2: banking down

    path = os.path.join(_OUT, "ship_sprites.bmp")
    img.save(path)
    print(f"  Created {path}  (48x16, 3 frames)")


# ---------------------------------------------------------------------------
# Enemy ships  (64x16 -- 4 types of 16x16)
# ---------------------------------------------------------------------------
def create_enemy_sprites():
    palette = [
        (0,   0,   0),    # 0: black
        (220, 30,  30),   # 1: red (scout)
        (180, 0,   180),  # 2: purple (weaver)
        (30,  180, 30),   # 3: green (diver)
        (200, 200, 50),   # 4: yellow (boss segment)
        (255, 255, 255),  # 5: white (eye / cockpit)
        (100, 100, 100),  # 6: grey (detail)
        (255, 140, 0),    # 7: orange (engine)
    ]
    img, d = _make_indexed(64, 16, palette)

    # -- Scout (type 0) at x=0 -- simple wedge facing left -----------------
    d.polygon([(1, 7), (1, 8), (10, 3), (14, 7), (14, 8),
               (10, 12)], fill=1)
    d.rectangle([11, 6, 13, 9], fill=6)
    d.point((12, 7), fill=5)   # cockpit
    d.rectangle([14, 7, 15, 8], fill=7)  # engine

    # -- Weaver (type 1) at x=16 -- curved body ----------------------------
    xo = 16
    d.ellipse([xo+2, 3, xo+12, 12], fill=2)
    d.rectangle([xo+0, 6, xo+4, 9], fill=2)   # nose
    d.rectangle([xo+11, 6, xo+15, 9], fill=6)  # tail
    d.rectangle([xo+14, 7, xo+15, 8], fill=7)  # engine
    d.point((xo+4, 7), fill=5)  # eye

    # -- Diver (type 2) at x=32 -- angular aggressive ----------------------
    xo = 32
    d.polygon([(xo+1, 7), (xo+1, 8), (xo+6, 3), (xo+12, 3),
               (xo+14, 7), (xo+14, 8), (xo+12, 12),
               (xo+6, 12)], fill=3)
    d.rectangle([xo+10, 6, xo+13, 9], fill=6)
    d.point((xo+11, 7), fill=5)
    d.rectangle([xo+14, 7, xo+15, 8], fill=7)
    # Fins
    d.line([(xo+8, 3), (xo+10, 1)], fill=3)
    d.line([(xo+8, 12), (xo+10, 14)], fill=3)

    # -- Boss segment (type 3) at x=48 -- large armoured block --------------
    xo = 48
    d.rectangle([xo+1, 1, xo+14, 14], fill=4)
    d.rectangle([xo+2, 2, xo+13, 13], fill=6)
    d.rectangle([xo+4, 5, xo+11, 10], fill=4)
    d.point((xo+6, 7), fill=5)
    d.point((xo+9, 7), fill=5)
    # Armour plates
    d.line([(xo+1, 4), (xo+14, 4)], fill=0)
    d.line([(xo+1, 11), (xo+14, 11)], fill=0)

    path = os.path.join(_OUT, "enemy_sprites.bmp")
    img.save(path)
    print(f"  Created {path}  (64x16, 4 types)")


# ---------------------------------------------------------------------------
# Player bullet  (6x4)
# ---------------------------------------------------------------------------
def create_bullet_sprite():
    palette = [
        (0,   0,   0),    # 0: black
        (0,   255, 255),  # 1: cyan
        (255, 255, 255),  # 2: white (bright core)
    ]
    img, d = _make_indexed(6, 4, palette)
    d.rectangle([0, 1, 4, 2], fill=1)
    d.rectangle([1, 0, 3, 3], fill=1)
    d.rectangle([2, 1, 4, 2], fill=2)  # bright core

    path = os.path.join(_OUT, "bullet_sprite.bmp")
    img.save(path)
    print(f"  Created {path}  (6x4)")


# ---------------------------------------------------------------------------
# Enemy bullet  (4x4)
# ---------------------------------------------------------------------------
def create_enemy_bullet_sprite():
    palette = [
        (0,   0,   0),    # 0: black
        (255, 60,  60),   # 1: red
        (255, 200, 100),  # 2: yellow core
    ]
    img, d = _make_indexed(4, 4, palette)
    d.ellipse([0, 0, 3, 3], fill=1)
    d.point((1, 1), fill=2)
    d.point((2, 2), fill=2)

    path = os.path.join(_OUT, "enemy_bullet_sprite.bmp")
    img.save(path)
    print(f"  Created {path}  (4x4)")


# ---------------------------------------------------------------------------
# Power-up sprites  (24x8 -- 3 types of 8x8)
# ---------------------------------------------------------------------------
def create_powerup_sprites():
    palette = [
        (0,   0,   0),    # 0: black
        (0,   150, 255),  # 1: blue (shield)
        (255, 220, 0),    # 2: yellow (rapid fire)
        (0,   220, 0),    # 3: green (extra life)
        (255, 255, 255),  # 4: white (icon detail)
    ]
    img, d = _make_indexed(24, 8, palette)

    # Shield (type 0) at x=0 -- circle with S
    d.ellipse([1, 1, 6, 6], fill=1)
    d.rectangle([3, 2, 4, 2], fill=4)
    d.point((2, 3), fill=4)
    d.rectangle([3, 4, 4, 4], fill=4)
    d.point((5, 5), fill=4)
    d.rectangle([3, 6, 4, 6], fill=4)

    # Rapid fire (type 1) at x=8 -- diamond with arrows
    xo = 8
    d.polygon([(xo+3, 0), (xo+7, 3), (xo+7, 4), (xo+3, 7),
               (xo+0, 4), (xo+0, 3)], fill=2)
    d.line([(xo+2, 3), (xo+5, 3)], fill=4)
    d.line([(xo+2, 4), (xo+5, 4)], fill=4)
    d.point((xo+5, 2), fill=4)
    d.point((xo+5, 5), fill=4)

    # Extra life (type 2) at x=16 -- heart / plus sign
    xo = 16
    d.ellipse([xo+1, 1, xo+6, 6], fill=3)
    d.rectangle([xo+3, 2, xo+4, 5], fill=4)  # vertical bar of +
    d.rectangle([xo+2, 3, xo+5, 4], fill=4)  # horizontal bar of +

    path = os.path.join(_OUT, "powerup_sprites.bmp")
    img.save(path)
    print(f"  Created {path}  (24x8, 3 types)")


# ---------------------------------------------------------------------------
# Explosion sprites  (48x16 -- 3 frames of 16x16)
# ---------------------------------------------------------------------------
def create_explosion_sprites():
    palette = [
        (0,   0,   0),    # 0: black
        (255, 60,  0),    # 1: red-orange (outer)
        (255, 160, 0),    # 2: orange (mid)
        (255, 240, 80),   # 3: yellow (core)
        (255, 255, 255),  # 4: white (flash)
        (100, 40,  0),    # 5: dark red (smoke)
    ]
    img, d = _make_indexed(48, 16, palette)

    # Frame 0: small initial burst
    d.ellipse([5, 5, 10, 10], fill=3)
    d.ellipse([4, 4, 11, 11], fill=2, outline=1)
    d.point((7, 7), fill=4)

    # Frame 1: larger mid-explosion
    xo = 16
    d.ellipse([xo+2, 2, xo+13, 13], fill=2, outline=1)
    d.ellipse([xo+4, 4, xo+11, 11], fill=3)
    d.point((xo+7, 7), fill=4)
    d.point((xo+6, 5), fill=4)
    d.point((xo+9, 10), fill=4)
    # Debris particles
    d.point((xo+1, 3), fill=1)
    d.point((xo+14, 5), fill=1)
    d.point((xo+3, 13), fill=1)
    d.point((xo+12, 1), fill=1)

    # Frame 2: dissipating smoke
    xo = 32
    d.ellipse([xo+3, 3, xo+12, 12], fill=5, outline=1)
    d.ellipse([xo+5, 5, xo+10, 10], fill=2)
    d.point((xo+7, 7), fill=3)
    # Scattered particles
    d.point((xo+1, 1), fill=5)
    d.point((xo+14, 2), fill=5)
    d.point((xo+2, 14), fill=5)
    d.point((xo+13, 13), fill=5)
    d.point((xo+0, 8), fill=1)
    d.point((xo+15, 7), fill=1)

    path = os.path.join(_OUT, "explosion_sprites.bmp")
    img.save(path)
    print(f"  Created {path}  (48x16, 3 frames)")


# ---------------------------------------------------------------------------
# Game Over splash  (240x135)  --  Space Impact themed
# ---------------------------------------------------------------------------
def create_game_over_screen():
    palette = [
        (0,   0,   10),   # 0: deep space black-blue background
        (200, 0,   0),    # 1: dark red (damaged hull)
        (255, 0,   0),    # 2: bright red (GAME OVER text)
        (255, 255, 255),  # 3: white (bright stars, text highlights)
        (40,  40,  70),   # 4: dim blue-grey (faint stars)
        (80,  80,  110),  # 5: medium grey-blue (medium stars)
        (255, 160, 0),    # 6: orange (explosions, fire)
        (255, 240, 80),   # 7: yellow (explosion cores)
        (0,   120, 200),  # 8: cyan (ship hull fragments)
        (0,   60,  130),  # 9: dark cyan (ship shadow)
        (140, 0,   0),    # 10: very dark red (text shadow)
        (60,  60,  60),   # 11: dark grey (debris)
        (180, 180, 200),  # 12: light grey (subtitle text)
        (100, 40,  0),    # 13: dark orange (smouldering)
        (200, 200, 220),  # 14: near-white (star twinkles)
        (20,  20,  40),   # 15: very dark blue (nebula tint)
    ]
    img, d = _make_indexed(240, 135, palette)

    import random
    random.seed(99)

    # --- Dense starfield background with depth layers --------------------
    # Layer 1: faint distant stars
    for _ in range(80):
        sx = random.randint(0, 239)
        sy = random.randint(0, 134)
        d.point((sx, sy), fill=4)

    # Layer 2: medium stars
    for _ in range(30):
        sx = random.randint(0, 239)
        sy = random.randint(0, 134)
        d.point((sx, sy), fill=5)

    # Layer 3: bright stars (some are 2px crosses for twinkle effect)
    for _ in range(12):
        sx = random.randint(2, 237)
        sy = random.randint(2, 132)
        d.point((sx, sy), fill=3)
        if random.random() > 0.5:
            d.point((sx - 1, sy), fill=14)
            d.point((sx + 1, sy), fill=14)
            d.point((sx, sy - 1), fill=14)
            d.point((sx, sy + 1), fill=14)

    # --- Subtle nebula wash in background --------------------------------
    for _ in range(40):
        nx = random.randint(60, 180)
        ny = random.randint(50, 100)
        d.point((nx, ny), fill=15)
        d.point((nx + 1, ny), fill=15)

    # --- Destroyed ship wreckage (centre-bottom) -------------------------
    # Main hull fragment (broken, tilted)
    cx, cy = 120, 95
    d.polygon([(cx - 12, cy), (cx - 4, cy - 8), (cx + 8, cy - 6),
               (cx + 14, cy), (cx + 10, cy + 6), (cx - 2, cy + 8),
               (cx - 10, cy + 4)], fill=9)
    d.polygon([(cx - 10, cy + 1), (cx - 3, cy - 6), (cx + 7, cy - 4),
               (cx + 12, cy + 1), (cx + 8, cy + 5), (cx - 1, cy + 6)], fill=8)
    # Cockpit canopy (cracked)
    d.rectangle([cx + 4, cy - 3, cx + 8, cy + 1], fill=9)
    d.point((cx + 5, cy - 2), fill=3)
    d.point((cx + 7, cy), fill=5)
    # Break line across hull
    d.line([(cx - 5, cy - 3), (cx + 3, cy + 5)], fill=0)
    d.line([(cx - 4, cy - 3), (cx + 4, cy + 5)], fill=11)

    # Detached wing fragment (upper-left of wreck)
    wx, wy = cx - 22, cy - 10
    d.polygon([(wx, wy), (wx + 8, wy - 3), (wx + 10, wy + 2),
               (wx + 4, wy + 5)], fill=9)
    d.polygon([(wx + 1, wy + 1), (wx + 7, wy - 1), (wx + 8, wy + 2),
               (wx + 4, wy + 4)], fill=8)

    # Small debris chunks scattered around
    debris_pos = [(cx + 20, cy - 8), (cx - 18, cy + 10), (cx + 25, cy + 5),
                  (cx - 25, cy - 2), (cx + 15, cy + 12), (cx - 8, cy - 14)]
    for dx, dy in debris_pos:
        d.rectangle([dx, dy, dx + 2, dy + 1], fill=11)

    # --- Explosion effects around the wreckage ---------------------------
    # Large explosion (right side of ship)
    ex1, ey1 = cx + 16, cy - 4
    d.ellipse([ex1 - 6, ey1 - 6, ex1 + 6, ey1 + 6], fill=6)
    d.ellipse([ex1 - 4, ey1 - 4, ex1 + 4, ey1 + 4], fill=7)
    d.point((ex1, ey1), fill=3)

    # Medium explosion (left-rear)
    ex2, ey2 = cx - 14, cy + 3
    d.ellipse([ex2 - 4, ey2 - 4, ex2 + 4, ey2 + 4], fill=6)
    d.ellipse([ex2 - 2, ey2 - 2, ex2 + 2, ey2 + 2], fill=7)

    # Small fire spots
    for fx, fy in [(cx + 2, cy - 5), (cx - 6, cy + 6), (cx + 10, cy + 4)]:
        d.ellipse([fx - 2, fy - 2, fx + 2, fy + 2], fill=13)
        d.point((fx, fy), fill=6)

    # Spark/particle trails radiating outward
    sparks = [(cx + 28, cy - 12), (cx - 30, cy - 6), (cx + 32, cy + 10),
              (cx - 26, cy + 14), (cx + 18, cy - 16), (cx - 20, cy - 14),
              (cx + 24, cy + 16), (cx - 14, cy + 16)]
    for sx, sy in sparks:
        sx = max(0, min(239, sx))
        sy = max(0, min(134, sy))
        d.point((sx, sy), fill=6)
        nx = max(0, min(239, sx + random.choice([-1, 1])))
        d.point((nx, sy), fill=7)

    # --- "GAME OVER" text with shadow (3px-thick block letters) ----------
    # Each letter: ~14px wide, 18px tall, 3px stroke width
    # Total "GAME OVER" width: 8 letters * ~16px spacing = ~176px
    # Centred: (240 - 176) / 2 = 32
    base_x = 18
    y0 = 16
    t  = 3   # stroke thickness

    def _block_letter(shapes, x_off, color, shadow_color=None):
        """Draw block-letter rectangles. shapes: list of (x, y, w, h) tuples."""
        if shadow_color is not None:
            for rx, ry, rw, rh in shapes:
                d.rectangle([x_off + rx + 1, y0 + ry + 1,
                             x_off + rx + rw, y0 + ry + rh], fill=shadow_color)
        for rx, ry, rw, rh in shapes:
            d.rectangle([x_off + rx, y0 + ry,
                         x_off + rx + rw - 1, y0 + ry + rh - 1], fill=color)

    # G
    _block_letter([
        (0, 0, 14, t),       # top bar
        (0, 0, t, 18),       # left bar
        (0, 15, 14, t),      # bottom bar
        (11, 9, t, 9),       # right lower bar
        (6, 9, 8, t),        # middle bar
    ], base_x, 2, 10)

    # A
    _block_letter([
        (0, 0, 14, t),       # top bar
        (0, 0, t, 18),       # left bar
        (11, 0, t, 18),      # right bar
        (0, 8, 14, t),       # middle bar
    ], base_x + 20, 2, 10)

    # M
    _block_letter([
        (0, 0, t, 18),       # left bar
        (13, 0, t, 18),      # right bar
        (t, 0, 3, 8),        # left diagonal
        (6, 4, 4, 6),        # centre point
        (10, 0, 3, 8),       # right diagonal
    ], base_x + 40, 2, 10)

    # E
    _block_letter([
        (0, 0, 14, t),       # top bar
        (0, 0, t, 18),       # left bar
        (0, 8, 12, t),       # middle bar
        (0, 15, 14, t),      # bottom bar
    ], base_x + 60, 2, 10)

    # (space gap of ~12px)

    # O
    _block_letter([
        (0, 0, 14, t),       # top bar
        (0, 0, t, 18),       # left bar
        (11, 0, t, 18),      # right bar
        (0, 15, 14, t),      # bottom bar
    ], base_x + 86, 2, 10)

    # V
    _block_letter([
        (0, 0, t, 12),       # left upper
        (11, 0, t, 12),      # right upper
        (2, 10, t + 1, 5),   # left lower diagonal
        (9, 10, t + 1, 5),   # right lower diagonal
        (5, 14, 6, t + 1),   # bottom point
    ], base_x + 106, 2, 10)

    # E
    _block_letter([
        (0, 0, 14, t),
        (0, 0, t, 18),
        (0, 8, 12, t),
        (0, 15, 14, t),
    ], base_x + 126, 2, 10)

    # R
    _block_letter([
        (0, 0, 14, t),       # top bar
        (0, 0, t, 18),       # left bar
        (11, 0, t, 10),      # right upper bar
        (0, 8, 14, t),       # middle bar
        (7, 11, t + 1, 3),   # diagonal connector
        (10, 13, t + 1, 5),  # right lower leg
    ], base_x + 146, 2, 10)

    # --- "SPACE IMPACT" title (small, above GAME OVER) -------------------
    # Thin decorative line
    d.rectangle([30, 10, 210, 10], fill=5)
    d.rectangle([30, 12, 210, 12], fill=4)

    # --- Subtitle line below GAME OVER -----------------------------------
    d.rectangle([50, 40, 190, 40], fill=5)

    # --- "SCORE" label area (placeholder box for the view's text overlay) -
    # Thin bordered box
    d.rectangle([65, 50, 175, 66], fill=0, outline=5)
    # "SCORE" text pixels (simple 5x5 font approximation)
    # S
    sx0, sy0 = 80, 54
    d.rectangle([sx0, sy0, sx0 + 4, sy0], fill=12)
    d.point((sx0, sy0 + 1), fill=12)
    d.rectangle([sx0, sy0 + 2, sx0 + 4, sy0 + 2], fill=12)
    d.point((sx0 + 4, sy0 + 3), fill=12)
    d.rectangle([sx0, sy0 + 4, sx0 + 4, sy0 + 4], fill=12)
    # C
    sx0 += 7
    d.rectangle([sx0, sy0, sx0 + 4, sy0], fill=12)
    d.point((sx0, sy0 + 1), fill=12)
    d.point((sx0, sy0 + 2), fill=12)
    d.point((sx0, sy0 + 3), fill=12)
    d.rectangle([sx0, sy0 + 4, sx0 + 4, sy0 + 4], fill=12)
    # O
    sx0 += 7
    d.rectangle([sx0, sy0, sx0 + 4, sy0], fill=12)
    d.point((sx0, sy0 + 1), fill=12)
    d.point((sx0 + 4, sy0 + 1), fill=12)
    d.point((sx0, sy0 + 2), fill=12)
    d.point((sx0 + 4, sy0 + 2), fill=12)
    d.point((sx0, sy0 + 3), fill=12)
    d.point((sx0 + 4, sy0 + 3), fill=12)
    d.rectangle([sx0, sy0 + 4, sx0 + 4, sy0 + 4], fill=12)
    # R
    sx0 += 7
    d.rectangle([sx0, sy0, sx0 + 4, sy0], fill=12)
    d.point((sx0, sy0 + 1), fill=12)
    d.point((sx0 + 4, sy0 + 1), fill=12)
    d.rectangle([sx0, sy0 + 2, sx0 + 4, sy0 + 2], fill=12)
    d.point((sx0, sy0 + 3), fill=12)
    d.point((sx0 + 3, sy0 + 3), fill=12)
    d.point((sx0, sy0 + 4), fill=12)
    d.point((sx0 + 4, sy0 + 4), fill=12)
    # E
    sx0 += 7
    d.rectangle([sx0, sy0, sx0 + 4, sy0], fill=12)
    d.point((sx0, sy0 + 1), fill=12)
    d.rectangle([sx0, sy0 + 2, sx0 + 3, sy0 + 2], fill=12)
    d.point((sx0, sy0 + 3), fill=12)
    d.rectangle([sx0, sy0 + 4, sx0 + 4, sy0 + 4], fill=12)

    # --- Bottom decorative elements --------------------------------------
    # Thin scan lines at very bottom
    d.rectangle([0, 125, 239, 125], fill=4)
    d.rectangle([0, 130, 239, 130], fill=15)
    d.rectangle([0, 134, 239, 134], fill=4)

    # Small "PRESS BUTTON" hint as dot pattern near bottom
    hint_y = 120
    for hx in range(78, 162, 3):
        d.point((hx, hint_y), fill=5)

    path = os.path.join(_OUT, "Game_Over.bmp")
    img.save(path)
    print(f"  Created {path}  (240x135, Space Impact themed)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def create_all_sprites():
    """Generate all sprite files for Space Impact."""
    os.makedirs(_OUT, exist_ok=True)

    print("Generating Space Impact sprite sheets...")
    print("-" * 50)

    try:
        create_ship_sprites()
        create_enemy_sprites()
        create_bullet_sprite()
        create_enemy_bullet_sprite()
        create_powerup_sprites()
        create_explosion_sprites()
        create_game_over_screen()

        print("-" * 50)
        print("\nSuccess! Created sprite files in:", _OUT)
        print("  - ship_sprites.bmp       (48x16,  3 frames)")
        print("  - enemy_sprites.bmp      (64x16,  4 types)")
        print("  - bullet_sprite.bmp      (6x4)")
        print("  - enemy_bullet_sprite.bmp(4x4)")
        print("  - powerup_sprites.bmp    (24x8,   3 types)")
        print("  - explosion_sprites.bmp  (48x16,  3 frames)")
        print("  - Game_Over.bmp          (240x135)")
        print("\nCopy the Sprites/ folder to your CircuitPython board root.")

    except Exception as e:
        print(f"\nError generating sprites: {e}")
        print("Make sure Pillow is installed:  pip install pillow")
        raise


if __name__ == "__main__":
    create_all_sprites()
