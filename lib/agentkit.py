#!/usr/bin/env python3
"""Isolated-interpreter entry point for the shared agentkit CLI."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from agentkit_core.cli import main
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
if __name__ == '__main__':
    sys.exit(main())
