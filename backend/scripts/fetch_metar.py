#!/usr/bin/env python3
"""CLI entrypoint for fetching latest METAR."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running directly from repository root without package install.
REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "backend" / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from tempest.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
