import sys
from pathlib import Path

# Add repo root to sys.path so `from lib.xxx import yyy` works from any test file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
