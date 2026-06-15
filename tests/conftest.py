"""Ensure the project root (fitfindr/) is importable so `from tools import ...` works
regardless of the directory pytest is invoked from."""

import os
import sys

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
