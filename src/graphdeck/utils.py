import os, re

def slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "topic"

def ensure_dir(d: str) -> None:
    os.makedirs(d, exist_ok=True)
