#!/usr/bin/env python3
"""Compatibility wrapper. Use `python agent_d.py ...` as the primary command."""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent_d import main


if __name__ == "__main__":
    main()
