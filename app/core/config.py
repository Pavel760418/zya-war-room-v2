from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"

# Prefer the "fixed" pilot name when present; otherwise the tracked template.
_CANDIDATES = (
    DATA_DIR / "war-room-template-2-no-traffic-fixed.xlsx",
    DATA_DIR / "war-room-template-2-no-traffic.xlsx",
)
DEFAULT_EXCEL_FILE = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[-1])
