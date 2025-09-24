from __future__ import annotations
import os, json, time, hashlib
from typing import Any, Dict, List
from pathlib import Path
from ddgs import DDGS
from trafilatura import fetch_url, extract

ASSET_DIR = Path("./data/assets")
FAST = os.getenv("GRAPHDECK_FAST") == "1"

def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:32]

def ddg_text_search(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    if FAST:
        max_results = min(max_results, 4)
    out: List[Dict[str, Any]] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results, safesearch="moderate"):
            out.append({"url": r.get("href") or r.get("url"), "title": r.get("title"), "snippet": r.get("body"), "source": "ddg", "content": None})
    if not FAST:
        for s in out[:6]:
            u = s.get("url")
            if not u: continue
            try:
                html = fetch_url(u, no_ssl=True, user_agent="graphdeck/1.0")
                text = extract(html, include_comments=False, include_images=False) if html else None
                if text and len(text) > 300:
                    s["content"] = text[:20000]
            except Exception:
                pass
    return out

def ddg_image_search(query: str, max_images: int = 4) -> List[Dict[str, Any]]:
    if FAST:
        return []
    imgs: List[Dict[str, Any]] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.images(query, max_results=max_images, safesearch="moderate", size=None, type_image=None, layout=None, color=None, license_image=None):
                imgs.append({"image_url": r.get("image") or r.get("image_url") or r.get("thumbnail"), "title": r.get("title"), "source": "ddg", "page_url": r.get("url") or r.get("source")})
    except Exception as e:
        print(f"⚠️  Image search failed: {e}")
        print("Continuing with text research only...")
    return imgs

def download_images(items: List[Dict[str, Any]]) -> None:
    import requests
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for it in items:
        url = it.get("image_url")
        if not url: continue
        try:
            fn = ASSET_DIR / f"{_sha(url)}.jpg"
            if not fn.exists():
                r = requests.get(url, timeout=15)
                if r.ok: fn.write_bytes(r.content)
            it["local_path"] = str(fn.resolve())
        except Exception:
            pass

def research_topic(topic: str, max_sources: int = 12, max_images: int = 6) -> Dict[str, Any]:
    if FAST:
        max_sources = min(max_sources, 4)
        max_images = 0
    sources = ddg_text_search(topic, max_results=max_sources)
    images = ddg_image_search(topic, max_images=max_images)
    download_images(images)
    return {"topic": topic, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "sources": sources, "images": images}

