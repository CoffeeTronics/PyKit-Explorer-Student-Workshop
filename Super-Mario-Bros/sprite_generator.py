"""
Simple Sprite Generator for CircuitPython Mario
Creates indexed BMP files suitable for displayio

This script generates simple pixel art sprites for Mario, Goombas, and blocks.
Run on your host computer with Python 3, then copy the .bmp files to your CircuitPython board.

Requirements:
    pip install pillow
"""

from PIL import Image, ImageDraw

def create_mario_sprites():
    """Create Mario sprite sheet with standing, walking, and jumping frames"""
    # 48x16 image (3 frames of 16x16)
    img = Image.new('P', (48, 16))
    
    # Define a simple palette (16 colors for compatibility)
    palette = [
        0, 0, 0,         # 0: Black
        255, 0, 0,       # 1: Red (Mario's shirt)
        0, 0, 255,       # 2: Blue (Mario's overalls)
        255, 200, 150,   # 3: Skin color
        139, 69, 19,     # 4: Brown (hair/shoes)
        255, 255, 255,   # 5: White
    ] + [0] * 30  # Fill rest with black
    
    img.putpalette(palette)
    draw = ImageDraw.Draw(img)
    
    # Frame 0: Standing Mario (16x16)
    # Head
    draw.rectangle([5, 2, 10, 7], fill=3)  # Face
    draw.rectangle([4, 2, 11, 3], fill=4)  # Hair
    draw.point((6, 4), fill=0)  # Eye
    draw.point((9, 4), fill=0)  # Eye
    
    # Body
    draw.rectangle([5, 8, 10, 12], fill=1)  # Red shirt
    draw.rectangle([4, 9, 11, 10], fill=2)  # Blue straps
    
    # Legs
    draw.rectangle([5, 13, 7, 15], fill=2)   # Left leg
    draw.rectangle([8, 13, 10, 15], fill=2)  # Right leg
    draw.rectangle([4, 15, 6, 15], fill=4)   # Left shoe
    draw.rectangle([9, 15, 11, 15], fill=4)  # Right shoe
    
    # Frame 1: Walking Mario (offset by 16 pixels)
    x_offset = 16
    # Head
    draw.rectangle([5+x_offset, 2, 10+x_offset, 7], fill=3)
    draw.rectangle([4+x_offset, 2, 11+x_offset, 3], fill=4)
    draw.point((6+x_offset, 4), fill=0)
    draw.point((9+x_offset, 4), fill=0)
    
    # Body
    draw.rectangle([5+x_offset, 8, 10+x_offset, 12], fill=1)
    draw.rectangle([4+x_offset, 9, 11+x_offset, 10], fill=2)
    
    # Legs (walking pose)
    draw.rectangle([4+x_offset, 13, 6+x_offset, 15], fill=2)   # Left leg forward
    draw.rectangle([9+x_offset, 13, 11+x_offset, 15], fill=2)  # Right leg back
    draw.rectangle([3+x_offset, 15, 5+x_offset, 15], fill=4)
    draw.rectangle([10+x_offset, 15, 12+x_offset, 15], fill=4)
    
    # Frame 2: Jumping Mario (offset by 32 pixels)
    x_offset = 32
    # Head
    draw.rectangle([5+x_offset, 2, 10+x_offset, 7], fill=3)
    draw.rectangle([4+x_offset, 2, 11+x_offset, 3], fill=4)
    draw.point((6+x_offset, 4), fill=0)
    draw.point((9+x_offset, 4), fill=0)
    
    # Body
    draw.rectangle([5+x_offset, 8, 10+x_offset, 12], fill=1)
    draw.rectangle([4+x_offset, 9, 11+x_offset, 10], fill=2)
    
    # Legs (jumping pose)
    draw.rectangle([3+x_offset, 13, 5+x_offset, 15], fill=2)
    draw.rectangle([10+x_offset, 13, 12+x_offset, 15], fill=2)
    
    img.save('mario_sprites.bmp')
    print("Created mario_sprites.bmp (48x16, 3 frames)")

def create_goomba_sprites():
    """Create Goomba enemy sprite sheet"""
    # 32x16 image (2 frames for walk animation)
    img = Image.new('P', (32, 16))
    
    palette = [
        0, 0, 0,         # 0: Black
        139, 69, 19,     # 1: Brown (body)
        210, 105, 30,    # 2: Light brown
        255, 255, 255,   # 3: White (eyes)
    ] + [0] * 36
    
    img.putpalette(palette)
    draw = ImageDraw.Draw(img)
    
    # Frame 0: Goomba standing
    # Body
    draw.ellipse([3, 4, 12, 13], fill=1)
    draw.rectangle([5, 6, 10, 11], fill=2)  # Lighter belly
    
    # Eyes
    draw.ellipse([5, 7, 7, 9], fill=3)   # Left eye white
    draw.ellipse([8, 7, 10, 9], fill=3)  # Right eye white
    draw.point((6, 8), fill=0)           # Left pupil
    draw.point((9, 8), fill=0)           # Right pupil
    
    # Feet
    draw.rectangle([3, 14, 5, 15], fill=1)
    draw.rectangle([10, 14, 12, 15], fill=1)
    
    # Eyebrows (angry look)
    draw.line([(4, 6), (7, 7)], fill=0)
    draw.line([(11, 6), (8, 7)], fill=0)
    
    # Frame 1: Goomba walking (offset by 16)
    x_offset = 16
    draw.ellipse([3+x_offset, 4, 12+x_offset, 13], fill=1)
    draw.rectangle([5+x_offset, 6, 10+x_offset, 11], fill=2)
    
    # Eyes
    draw.ellipse([5+x_offset, 7, 7+x_offset, 9], fill=3)
    draw.ellipse([8+x_offset, 7, 10+x_offset, 9], fill=3)
    draw.point((6+x_offset, 8), fill=0)
    draw.point((9+x_offset, 8), fill=0)
    
    # Feet (walking)
    draw.rectangle([2+x_offset, 14, 4+x_offset, 15], fill=1)
    draw.rectangle([11+x_offset, 14, 13+x_offset, 15], fill=1)
    
    # Eyebrows
    draw.line([(4+x_offset, 6), (7+x_offset, 7)], fill=0)
    draw.line([(11+x_offset, 6), (8+x_offset, 7)], fill=0)
    
    img.save('goomba_sprites.bmp')
    print("Created goomba_sprites.bmp (32x16, 2 frames)")

def create_block_sprites():
    """Create block sprite sheet (brick, question, pipe)"""
    # 48x16 image (3 block types)
    img = Image.new('P', (48, 16))
    
    palette = [
        0, 0, 0,         # 0: Black
        216, 120, 80,    # 1: Brick red
        252, 188, 0,     # 2: Question block yellow
        0, 170, 0,       # 3: Pipe green
        255, 255, 255,   # 4: White
        160, 82, 45,     # 5: Dark brick
    ] + [0] * 30
    
    img.putpalette(palette)
    draw = ImageDraw.Draw(img)
    
    # Brick block (0-15, 0-15)
    draw.rectangle([0, 0, 15, 15], fill=1, outline=5)
    # Brick pattern
    draw.line([(0, 4), (15, 4)], fill=5)
    draw.line([(0, 8), (15, 8)], fill=5)
    draw.line([(0, 12), (15, 12)], fill=5)
    draw.line([(8, 0), (8, 4)], fill=5)
    draw.line([(4, 4), (4, 8)], fill=5)
    draw.line([(12, 8), (12, 12)], fill=5)
    draw.line([(8, 12), (8, 15)], fill=5)
    
    # Question block (16-31, 0-15)
    x_offset = 16
    draw.rectangle([x_offset, 0, x_offset+15, 15], fill=2, outline=0)
    # Question mark
    draw.rectangle([x_offset+6, x_offset-11, x_offset+9, x_offset-9], fill=4)  # Top of ?
    draw.rectangle([x_offset+9, x_offset-11, x_offset+11, x_offset-6], fill=4) # Right of ?
    draw.rectangle([x_offset+6, x_offset-6, x_offset+9, x_offset-4], fill=4)   # Middle of ?
    draw.point((x_offset+7, x_offset-2), fill=4)  # Dot
    
    # Pipe block (32-47, 0-15)
    x_offset = 32
    draw.rectangle([x_offset, 0, x_offset+15, 15], fill=3, outline=0)
    # Pipe details
    draw.rectangle([x_offset+2, x_offset-14, x_offset+13, x_offset-13], fill=0)
    draw.rectangle([x_offset+2, 2, x_offset+13, 3], fill=0)
    draw.line([(x_offset+5, 0), (x_offset+5, 15)], fill=0)
    draw.line([(x_offset+10, 0), (x_offset+10, 15)], fill=0)
    
    img.save('block_sprites.bmp')
    print("Created block_sprites.bmp (48x16, 3 block types)")

def create_coin_sprite():
    """Create coin sprite"""
    img = Image.new('P', (8, 14))
    
    palette = [
        0, 0, 0,         # 0: Black (transparent)
        252, 188, 0,     # 1: Gold
        255, 215, 0,     # 2: Light gold
    ] + [0] * 45
    
    img.putpalette(palette)
    draw = ImageDraw.Draw(img)
    
    # Coin
    draw.ellipse([1, 2, 6, 11], fill=1, outline=2)
    draw.ellipse([2, 4, 5, 9], fill=2)  # Highlight
    
    img.save('coin_sprite.bmp')
    print("Created coin_sprite.bmp (8x14)")

def create_all_sprites():
    """Generate all sprite files"""
    print("Generating Mario sprite sheets...")
    print("-" * 40)
    
    try:
        create_mario_sprites()
        create_goomba_sprites()
        create_block_sprites()
        create_coin_sprite()
        
        print("-" * 40)
        print("\nSuccess! Created sprite files:")
        print("  - mario_sprites.bmp")
        print("  - goomba_sprites.bmp")
        print("  - block_sprites.bmp")
        print("  - coin_sprite.bmp")
        print("\nCopy these .bmp files to your CircuitPython board's root directory.")
        print("\nTo use in your code, load them with:")
        print("  sprite_sheet, palette = adafruit_imageload.load('/mario_sprites.bmp')")
        
    except Exception as e:
        print(f"\nError generating sprites: {e}")
        print("Make sure you have Pillow installed: pip install pillow")

if __name__ == "__main__":
    create_all_sprites()
