# code.py - Unified Game Launcher for PyKit Explorer
# ==================================================
#
# This launcher automatically discovers and cycles through games in the
# /games/ folder. Each game runs until game over or the user presses D11
# to switch to the next game.
#
# Launcher Flow:
# --------------
# 1. Initialize shared hardware (LCD, IMU, NeoPixels, Audio)
# 2. Discover games by scanning /games/ subfolders for BaseGame classes
# 3. Main loop:
#    a. Show transition screen with next game name (3 seconds)
#    b. Create fresh AudioOutput for the game
#    c. Instantiate game class with shared hardware
#    d. Call game.setup() to initialize game-specific resources
#    e. Call game.run(switch_detector) - runs until game over or D11 press
#    f. Call game.cleanup() to release game-specific resources
#    g. Deinit audio to free DAC
#    h. Cycle to next game and repeat
#
# Hardware Resources (shared across all games):
# ---------------------------------------------
# - lcd: LCDDisplay (240x135 ST7789 TFT)
# - imu: IMUSensor (ICM-20948 accelerometer/gyro)
# - px: NeoPixels (5 RGB LEDs at brightness 0.15)
# - audio: AudioOutput (created fresh for each game)
# - switch_btn: EdgeDetector on D11 (game switch button)
# - high_scores: HighScoreManager (NVM persistence)
#
# Adding New Games:
# -----------------
# See games/GAME_README.md for instructions on creating new games.
# Games are auto-discovered - just add a folder with __init__.py that
# exports a class inheriting from BaseGame.

import sys
sys.path.insert(0, "/API")

import time
import gc
import os
import board
import displayio
import terminalio
from adafruit_display_text import label as _label

from lcd_display import LCDDisplay
from imu_sensor import IMUSensor
from neopixels import NeoPixels
from audio_out import AudioOutput
from digital_io import EdgeDetector
from high_scores import HighScoreManager
from base_game import BaseGame

TRANSITION_DURATION = 3.0


def discover_games():
    games = []
    
    possible_paths = ["/games", "games", "./games"]
    games_path = None
    
    for path in possible_paths:
        try:
            entries = os.listdir(path)
            games_path = path
            print(f"Found games folder at: {path}")
            break
        except OSError:
            continue
    
    if games_path is None:
        print("ERROR: games folder not found")
        return games
    
    print(f"Games folder contents: {entries}")
    
    for name in entries:
        if name.startswith(".") or name.startswith("_"):
            continue
        if name.endswith(".md") or name.endswith(".txt") or name.endswith(".py"):
            continue
            
        folder_path = f"{games_path}/{name}"
        
        try:
            stat_result = os.stat(folder_path)
            is_dir = stat_result[0] & 0x4000
            if not is_dir:
                continue
        except OSError as e:
            print(f"  Cannot stat {folder_path}: {e}")
            continue
        
        init_path = f"{folder_path}/__init__.py"
        try:
            os.stat(init_path)
        except OSError:
            print(f"  Skipping {name}: no __init__.py")
            continue
        
        try:
            print(f"  Importing games.{name}...")
            module = __import__(f"games.{name}")
            submodule = getattr(module, name)
            
            for attr_name in dir(submodule):
                attr = getattr(submodule, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, BaseGame) and 
                    attr is not BaseGame):
                    games.append(attr)
                    print(f"  Loaded: {attr.NAME}")
                    break
        except Exception as e:
            print(f"  Error loading {name}: {e}")
    
    return games


def show_transition_screen(display, game_name):
    gc.collect()
    
    grp = displayio.Group()
    
    bg_bmp = displayio.Bitmap(240, 135, 1)
    bg_pal = displayio.Palette(1)
    bg_pal[0] = 0x000020
    grp.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
    
    title = _label.Label(
        terminalio.FONT,
        text="Next game...",
        color=0xFFFFFF,
        scale=2,
        anchor_point=(0.5, 0.5),
        anchored_position=(120, 50),
    )
    grp.append(title)
    
    name_label = _label.Label(
        terminalio.FONT,
        text=game_name,
        color=0x00FF00,
        scale=3,
        anchor_point=(0.5, 0.5),
        anchored_position=(120, 90),
    )
    grp.append(name_label)
    
    display.root_group = grp


def show_error(display, message):
    grp = displayio.Group()
    bg_bmp = displayio.Bitmap(240, 135, 1)
    bg_pal = displayio.Palette(1)
    bg_pal[0] = 0x400000
    grp.append(displayio.TileGrid(bg_bmp, pixel_shader=bg_pal))
    
    lbl = _label.Label(
        terminalio.FONT,
        text=message,
        color=0xFFFFFF,
        scale=2,
        anchor_point=(0.5, 0.5),
        anchored_position=(120, 67),
    )
    grp.append(lbl)
    display.root_group = grp


def clear_display(display):
    try:
        empty = displayio.Group()
        display.root_group = empty
    except:
        pass
    gc.collect()


def main():
    gc.collect()
    print("=" * 50)
    print("UNIFIED GAME LAUNCHER")
    print("=" * 50)
    print(f"Free RAM: {gc.mem_free()} bytes")
    
    print("\nInitializing hardware...")
    lcd = LCDDisplay()
    imu = IMUSensor()
    px = NeoPixels(num_pixels=5, brightness=0.15)
    
    switch_btn = EdgeDetector(board.D11)
    high_scores = HighScoreManager()
    
    px.fill((0, 0, 0))
    lcd.backlight_on()
    
    print("\nDiscovering games...")
    game_classes = discover_games()
    
    if not game_classes:
        print("ERROR: No games found!")
        show_error(lcd.display, "No games found!")
        while True:
            time.sleep(1)
    
    print(f"\nFound {len(game_classes)} game(s)")
    
    current_game_index = None
    current_game = None
    
    while True:
        # Cycle to next game in order
        current_game_index = 0 if current_game_index is None else (current_game_index + 1) % len(game_classes)
        game_class = game_classes[current_game_index]
        
        # Force cleanup before transition
        clear_display(lcd.display)
        gc.collect()
        print(f"Pre-switch RAM: {gc.mem_free()} bytes")
        
        print(f"\nSwitching to: {game_class.NAME}")
        show_transition_screen(lcd.display, game_class.NAME)
        px.fill((0, 0, 128))
        time.sleep(TRANSITION_DURATION)
        
        # Clear transition screen before game setup
        clear_display(lcd.display)
        gc.collect()
        
        # Create fresh audio for each game
        audio = AudioOutput()
        
        px.fill((0, 0, 0))
        gc.collect()
        current_game = game_class(lcd, imu, px, audio, high_scores)
        
        try:
            gc.collect()
            current_game.setup()
        except Exception as e:
            print(f"Setup error: {e}")
            if current_game:
                try:
                    current_game.cleanup()
                except:
                    pass
            try:
                audio.deinit()
            except:
                pass
            clear_display(lcd.display)
            gc.collect()
            continue
        
        try:
            switch_requested = current_game.run(switch_btn)
        except Exception as e:
            print(f"Runtime error: {e}")
            switch_requested = True
        
        # Cleanup after game
        try:
            current_game.cleanup()
        except Exception as e:
            print(f"Cleanup error: {e}")
        
        # Deinit audio to free DAC
        try:
            audio.deinit()
        except:
            pass
        
        current_game = None
        clear_display(lcd.display)
        gc.collect()
        print(f"Switched. Free RAM: {gc.mem_free()} bytes")


if __name__ == "__main__":
    main()
