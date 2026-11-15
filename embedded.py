"""Build-time constants — edit before building the EXE. No config files at runtime."""

SERVER_BASE_URL = ""

# True for self-signed server cert; False for Let's Encrypt / public CA.
INSECURE_TLS = False

# Local web map port (only listens on 127.0.0.1).
WEB_PORT = 8765

CLIENT_VERSION = "1.0.0"

# UI language: "en" (default) | "ru"
UI_LANG = "en"

# Stock app key (same on all clients + server). Wiped after successful enroll patch.
APP_KEY = ""

# Per-device secret (64 hex). Placeholder until enroll patches the slot in the binary.
DEVICE_SECRET = ""
DEVICE_SECRET_PLACEHOLDER = ""

# Unique ASCII marker kept in frozen EXE so patch can find the 64-hex slot.
DEVICE_SECRET_SLOT_PREFIX = "AMDB_DEVSEC_SLOT_v1="
# noqa: keep as bytes constant for PyInstaller archive
_KEEP_DEVICE_SECRET_SLOT = (DEVICE_SECRET_SLOT_PREFIX + DEVICE_SECRET_PLACEHOLDER).encode("ascii")
