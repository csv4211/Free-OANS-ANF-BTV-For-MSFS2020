"""Build channel flags. build.ps1 overwrites this file before PyInstaller, then restores defaults.

default  РІР‚вЂќ auto-update enabled (site / direct distribution)
fsto     РІР‚вЂќ flightsim.to build: no auto-update mechanism
"""

from __future__ import annotations

# "default" | "fsto"
BUILD_CHANNEL = "default"

# False for flightsim.to builds
AUTO_UPDATE = True

# Shown in window title / version label when non-empty (e.g. "fs.to")
CHANNEL_LABEL = ""
