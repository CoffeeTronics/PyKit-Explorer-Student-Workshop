"""
base_game.py - Base class for all games
=======================================

All games must inherit from BaseGame and implement the required methods.
See games/GAME_README.md for detailed instructions on creating new games.
"""


class BaseGame:
    """Abstract base class that all games must inherit from.

    Games receive shared hardware resources in the constructor and must
    implement setup(), run(), and cleanup() methods.
    """

    NAME = "Unnamed Game"
    HIGH_SCORE_SLOT = -1  # Must be overridden with unique slot number (0-29)

    def __init__(self, lcd, imu, neopixels, audio, high_score_manager):
        """Initialize with shared hardware resources.

        Parameters
        ----------
        lcd : LCDDisplay
            Shared LCD display instance
        imu : IMUSensor
            Shared IMU sensor instance
        neopixels : NeoPixels
            Shared NeoPixel strip instance
        audio : AudioOutput
            Shared audio output instance
        high_score_manager : HighScoreManager
            Shared high score persistence manager
        """
        self.lcd = lcd
        self.imu = imu
        self.px = neopixels
        self.audio = audio
        self.high_scores = high_score_manager

    def setup(self):
        """Initialize game-specific resources.

        Called once before the game loop starts. Use this to:
        - Create display groups and sprites
        - Initialize game-specific inputs (buttons, touch pads)
        - Set up the game model and view
        - Calibrate sensors if needed

        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement setup()")

    def run(self, switch_detector):
        """Main game loop.

        Parameters
        ----------
        switch_detector : EdgeDetector
            Edge detector for D11 pin. Check switch_detector.fell each
            iteration to detect game switch request.

        Returns
        -------
        bool
            True if a game switch was requested (D11 falling edge detected),
            False if the game exited for another reason.

        Must be implemented by subclasses. Typical structure:

            while True:
                switch_detector.update()
                if switch_detector.fell:
                    return True

                # Game logic here...
                time.sleep(0.033)
        """
        raise NotImplementedError("Subclasses must implement run()")

    def cleanup(self):
        """Release game-specific resources before switching.

        Called after run() returns. Use this to:
        - deinit() any game-specific inputs (buttons, touch pads)
        - Clear display groups
        - Stop any playing audio
        - Reset NeoPixels to off state

        Must be implemented by subclasses.
        """
        raise NotImplementedError("Subclasses must implement cleanup()")

    def get_high_score(self):
        """Get this game's high score from persistent storage."""
        if self.HIGH_SCORE_SLOT < 0:
            return 0
        return self.high_scores.get(self.HIGH_SCORE_SLOT)

    def set_high_score(self, score):
        """Set this game's high score in persistent storage."""
        if self.HIGH_SCORE_SLOT < 0:
            return
        self.high_scores.set(self.HIGH_SCORE_SLOT, score)
