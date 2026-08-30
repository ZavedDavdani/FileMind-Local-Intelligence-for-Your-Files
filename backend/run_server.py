"""Server runner entry point for PyInstaller standalone bundling."""

import sys
import os

# Ensure backend root is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app.main import start

if __name__ == "__main__":
    start()
