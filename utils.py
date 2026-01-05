# utils.py
from datetime import datetime, timezone
import re

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def clean_text(s: str) -> str:
    s = s or ""
    return re.sub(r"\s+", " ", s).strip()