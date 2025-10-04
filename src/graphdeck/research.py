from __future__ import annotations

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=False)

import os, json, time, hashlib, re
from typing import Any, Dict, List, Optional
from pathlib import Path
from ddgs import DDGS
from trafilatura import extract as trafi_extract
import requests

ASSET_DIR = Path("./data/assets")
FAST = os.getenv("GRAPHDECK_FAST") == "1"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 graphdeck/1.3")
TIMEOUT = 18

def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()[:32]

def _safe_get(url: str) -> Optional[requests.Response]:
    try:
        return requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT, allow_redirects=True)
    except Exception:
        return None

def _extract_text(html: str, url: str) -> Optional[str]:
    # Ask trafilatura to favor recall and tolerate messy markup
    try:
        txt = trafi_extract(html, include_comments=False, include_images=False, favor_precision=False, url=url)
        if txt and len(txt.strip()) > 300:
            return re.sub(r"\s+", " ", txt.strip())[:20000]
    except Exception:
        pass
    return None

def ddg_text_search(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    if FAST:
        max_results = min(max_results, 6)
    out: List[Dict[str, Any]] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results, safesearch="moderate"):
            url = r.get("href") or r.get("url")
            out.append({
                "url": url,
                "title": r.get("title"),
                "snippet": r.get("body"),
                "source": "ddg",
                "content": None,
            })
    # Enrich with page text even in FAST (lightweight, short timeout)
    for s in out:
        u = s.get("url")
        if not u:
            continue
        resp = _safe_get(u)
        if not resp or not resp.ok:
            continue
        ctype = resp.headers.get("Content-Type", "").lower()
        if "text/html" not in ctype:
            continue
        text = _extract_text(resp.text, u)
        if text:
            s["content"] = text
        # Guarantee we never leave content None; fall back to snippet/title
        if not s.get("content"):
            s["content"] = (s.get("snippet") or s.get("title") or "")[:2000]
    return out

def ddg_image_search(query: str, max_images: int = 4) -> List[Dict[str, Any]]:
    if FAST:
        max_images = min(max_images, 2)
    imgs: List[Dict[str, Any]] = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.images(query, max_results=max_images, safesearch="moderate"):
                imgs.append({
                    "image_url": r.get("image") or r.get("image_url") or r.get("thumbnail"),
                    "title": r.get("title"),
                    "source": "ddg",
                    "page_url": r.get("url") or r.get("source")
                })
    except Exception:
        pass
    return imgs

def download_images(items: List[Dict[str, Any]]) -> None:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    for it in items:
        url = it.get("image_url")
        if not url:
            continue
        try:
            fn = ASSET_DIR / f"{_sha(url)}.jpg"
            if not fn.exists():
                r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
                if r.ok:
                    fn.write_bytes(r.content)
            it["local_path"] = str(fn.resolve())
        except Exception:
            pass

def research_topic(topic: str, max_sources: int = 12, max_images: int = 6) -> Dict[str, Any]:
    sources = ddg_text_search(topic, max_results=max_sources)
    images = ddg_image_search(topic, max_images=max_images)
    download_images(images)
    # never ship empty bundle
    return {
        "topic": topic,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "sources": sources,
        "images": images
    }


