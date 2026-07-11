"""Shared test setup: headless SDL before pygame is ever imported."""

import os

# Must happen before any pygame import anywhere in the test run.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
