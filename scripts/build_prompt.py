#!/usr/bin/env python3
"""
Build worker prompt for the current round of tasks. (Standalone script)

This is a thin wrapper that imports from the package.
See src/scheduler_harness/build_prompt.py for full documentation.

Usage:
    python3 scripts/build_prompt.py --tasks '[{"id":"T001","description":"Do something"}]'
    python3 scripts/build_prompt.py --tasks-file ./current_tasks.json
    python3 scripts/build_prompt.py --tasks-file ./tasks.json --template my_prompt.md
    python3 scripts/build_prompt.py --init-template
    python3 scripts/build_prompt.py --list-placeholders
"""

import sys
from pathlib import Path

# Add src/ to path so we can import the package
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))

from scheduler_harness.build_prompt import main

if __name__ == '__main__':
    main()
