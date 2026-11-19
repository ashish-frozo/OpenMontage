"""Absolute-path entry point for MCP clients launched outside the repository."""
import os
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)

from content_factory.server import main

if __name__ == "__main__":
    main()
