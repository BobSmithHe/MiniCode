#!/usr/bin/env python3
"""Launch script for the modular Claude Code agent harness.

Usage:
  python run.py
"""

import sys
from pathlib import Path

# Put the project root on sys.path so ``import Agent`` works.
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from Agent.main import main

if __name__ == "__main__":
    main()
