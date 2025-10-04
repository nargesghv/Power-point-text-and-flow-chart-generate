from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import textwrap
import html as _html
from typing import Dict, Any, List, Optional

from .llm import _chat

# -----------------------------------------------------------------------------
# Flags
# -----------------------------------------------------------------------------
FAST = os.getenv("GRAPHDECK_FAST", "0") == "1"
DEBUG = os.getenv("GRAPHDECK_DEBUG", "0") == "1"

# -----------------------------------------------------------------------------
# Mermaid proposal (deterministic fallback)
# -----------------------------------------------------------------------------
def propose_mermaid(topic: str) -> str:
    safe = (topic or "Topic").strip().replace("\n", " ")[:100]
    return textwrap.dedent(f"""
    flowchart TD
      classDef title fill:#202a45,stroke:#6b86ff,stroke-width:1px,color:#e8ecff,rx:8,ry:8
      classDef block fill:#121a2b,stroke:#6b86ff,stroke-width:1px,color:#e8ecff,rx:8,ry:8
      classDef warn  fill:#2b2312,stroke:#fbbf24,color:#ffeab6,rx:8,ry:8
      A["{safe}"]:::title --> B[Key Areas]:::block
      B --> C[Research]:::block
      B --> D[Data & Trends]:::block
      B --> E[Use Cases]:::block
      C --> F[Sources & Notes]:::block
      D --> G[Signals / Benchmarks]:::block
      E --> H[Impact / Outcomes]:::block
    """).strip() + "\n"

LLM_MERMAID_SYSTEM = """You write high-quality Mermaid (flowchart) for business/tech slides.
Requirements:
- Direction: TD (top->down); succinct labels (<=6 words).
- Use a dark theme via classDef.
- Avoid overlapping edges; group logically.
Return only Mermaid code (no backticks)."""

def _build_research_hint(research: Optional[Dict[str, Any]]) -> str:
    if not research:
        return ""
    parts: List[str] = []
    summary = (research.get("summary") or "").strip()
    if summary:
        parts.append("SUMMARY:\n" + summary[:800])
    for s in (research.get("sources") or [])[:6]:
        title = (s.get("title") or "")[:100]
        url = (s.get("url") or "")[:160]
        if title or url:
            parts.append(f"- {title} — {url}")
    return "\n".join(parts)

def _looks_like_mermaid(s: str) -> bool:
    s = (s or "").strip().lower()
    return s.startswith("flowchart") and "td" in s[:40]  # quick sanity filter

def mermaid_from_llm(topic: str, research: Optional[Dict[str, Any]] = None) -> str:
    hint = _build_research_hint(research)
    payload = {"topic": topic, "hint": hint}
    prompt = "Create a Mermaid flowchart for the payload below. Return ONLY Mermaid.\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    try:
        mermaid = _chat(LLM_MERMAID_SYSTEM, prompt, temperature=0.2, max_tokens=700)
    except Exception as e:
        if DEBUG:
            import traceback; print("mermaid_from_llm error:", e); traceback.print_exc()
        mermaid = ""
    if not isinstance(mermaid, str) or not _looks_like_mermaid(mermaid):
        return propose_mermaid(topic)
    return mermaid.strip()

# -----------------------------------------------------------------------------
# Helpers for deterministic build
# -----------------------------------------------------------------------------
def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", (s or "").strip())[:40] or "N"

def _esc(s: str) -> str:
    return _html.escape((s or "").strip())

def _split_colon_subitems(bullet: str):
    if ":" in bullet:
        h, t = bullet.split(":", 1)
        items = [p.strip() for p in re.split(r",|;|\u2022|\|", t) if p.strip()]
        if items:
            return h.strip(), items
    return bullet, None

def build_mermaid_from_title_bullets(title: str, bullets: List[str]) -> str:
    title = (title or "Slide").strip()
    bullets = [b for b in (bullets or []) if str(b).strip()]
    root_id = "T_" + _slug(title)
    lines = [
        "flowchart TD",
        "  classDef title fill:#202a45,stroke:#6b86ff,stroke-width:1px,color:#e8ecff,rx:8,ry:8",
        "  classDef block fill:#121a2b,stroke:#6b86ff,stroke-width:1px,color:#e8ecff,rx:8,ry:8",
        "  classDef warn  fill:#2b2312,stroke:#fbbf24,color:#ffeab6,rx:8,ry:8",
        f'  {root_id}["{_esc(title)}"]:::title',
    ]
    for i, raw in enumerate(bullets, 1):
        txt = str(raw).strip()
        node = f"B{i}_{_slug(txt)}"
        is_decision = ("?" in txt) or txt.lower().startswith("decision")
        br_open, br_close = ("{","}") if is_decision else ("[","]")
        klass = "warn" if is_decision else "block"

        if "->" in txt and not is_decision:
            parts = [p.strip() for p in txt.split("->") if p.strip()]
            head = f"{node}_S0"
            lines.append(f'  {head}{br_open}"{_esc(parts[0])}"{br_close}:::{klass}')
            lines.append(f"  {root_id} --> {head}")
            prev = head
            for j, step in enumerate(parts[1:], 1):
                sid = f"{node}_S{j}"
                lines.append(f'  {sid}["{_esc(step)}"]:::block')
                lines.append(f"  {prev} --> {sid}")
                prev = sid
            continue

        head, items = _split_colon_subitems(txt)
        if items:
            hid = f"{node}_H"
            lines.append(f'  {hid}{br_open}"{_esc(head)}"{br_close}:::{klass}')
            lines.append(f"  {root_id} --> {hid}")
            prev = hid
            for j, it in enumerate(items, 1):
                sid = f"{node}_I{j}"
                lines.append(f'  {sid}["{_esc(it)}"]:::block')
                lines.append(f"  {prev} --> {sid}")
                prev = sid
        else:
            lines.append(f'  {node}{br_open}"{_esc(txt)}"{br_close}:::{klass}')
            lines.append(f"  {root_id} --> {node}")
    return "\n".join(lines) + "\n"

# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------
VISUAL_PROMPT = """Make a single-slide HTML (1600x900) dark theme with a left SVG flow diagram and a right sidebar.
Tone: clean, modern, business. No external CSS.
INPUT:
{input_json}
"""

def html_visual_from_llm(payload: Dict[str, Any]) -> str:
    prompt = VISUAL_PROMPT.format(input_json=json.dumps(payload, ensure_ascii=False, indent=2))
    return _chat("You produce polished, self-contained HTML slides.", prompt, temperature=0.2, max_tokens=1800 if FAST else 2000)

async def _render_html_async(html: str, out_img: str, width: int = 1600, height: int = 900, selector: str = "body") -> None:
    try:
        from playwright.async_api import async_playwright
    except Exception as e:
        # Playwright not installed — write an .html next to the target so there is still an artifact
        html_path = pathlib.Path(out_img).with_suffix(".html")
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
        if DEBUG:
            print("Playwright unavailable; wrote HTML instead:", html_path)
        return

    out_path = pathlib.Path(out_img)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": width, "height": height, "deviceScaleFactor": 1})
        await page.set_content(html, wait_until="networkidle")
        try:
            await page.wait_for_selector(selector, state="visible", timeout=8000)
            el = await page.query_selector(selector)
            if out_img.lower().endswith(".svg"):
                svg_html = await page.evaluate("el => el.outerHTML", el)
                out_path.write_text(svg_html, encoding="utf-8")
            else:
                if el:
                    await el.screenshot(path=str(out_path))
                else:
                    await page.screenshot(path=str(out_path), full_page=False)
        finally:
            await browser.close()

def render_html_to_image(html: str, out_img: str, width: int = 1600, height: int = 900, selector: str = "body") -> None:
    # If called inside an existing event loop (unlikely here), fallback to a new loop in a thread
    try:
        asyncio.get_running_loop()
        # Running inside an event loop: create a nested task via a new loop
        asyncio.run(_render_html_async(html, out_img, width, height, selector))
    except RuntimeError:
        # No loop running
        asyncio.run(_render_html_async(html, out_img, width, height, selector))

def _html_for_mermaid(mmd: str, width: int, height: int) -> str:
    return f"""<!doctype html>
<html><head><meta charset="utf-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net data:;">
<style>
html,body{{margin:0;background:#0b1020}}
.wrap{{width:{width}px;height:{height}px;display:flex;align-items:center;justify-content:center}}
.mermaid{{color:#e8ecff;font-family:ui-sans-serif,system-ui,-apple-system,Segoe UI,Roboto}}
</style>
<script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
</head>
<body>
  <div class="wrap"><div class="mermaid" id="diagram" style="width:{width}px;height:{height}px;">{mmd}</div></div>
  <script>
    mermaid.initialize({{ startOnLoad: true, theme: "dark", securityLevel: "loose" }});
    const obs = new MutationObserver(() => {{
      const svg = document.querySelector('#diagram svg');
      if (svg) {{ document.body.setAttribute('data-ready','1'); obs.disconnect(); }}
    }});
    obs.observe(document.getElementById('diagram'), {{ childList: true, subtree: true }});
  </script>
</body></html>"""

def render_mermaid(mmd: str, out_img: str, width: int = 1200, height: int = 800) -> None:
    html = _html_for_mermaid(mmd, width, height)
    render_html_to_image(html, out_img, width, height, selector="#diagram svg")

# -----------------------------------------------------------------------------
# Public APIs
# -----------------------------------------------------------------------------
def flowchart_from_title_bullets(
    title: str,
    bullets: List[str],
    out_path: str,
    *,
    research: Optional[Dict[str, Any]] = None,
    use_llm: bool = True,
    width: int = 1200,
    height: int = 800,
) -> str:
    if FAST:
        use_llm = False
    if use_llm:
        topic = f"{title} — " + "; ".join((bullets or [])[:6])
        mmd = mermaid_from_llm(topic, research=research)
        if not _looks_like_mermaid(mmd):
            mmd = build_mermaid_from_title_bullets(title, bullets)
    else:
        mmd = build_mermaid_from_title_bullets(title, bullets)
    render_mermaid(mmd, out_path, width=width, height=height)
    return out_path

def generate_flowchart_image(
    topic: str,
    out_img: str,
    use_llm: bool = True,
    width: int = 1200,
    height: int = 800,
    research: Optional[Dict[str, Any]] = None
) -> str:
    if FAST:
        use_llm = False
    mermaid = mermaid_from_llm(topic, research=research) if use_llm else propose_mermaid(topic)
    render_mermaid(mermaid, out_img, width=width, height=height)
    return out_img

def html_visual_from_llm(payload: Dict[str, Any]) -> str:
    prompt = VISUAL_PROMPT.format(input_json=json.dumps(payload, ensure_ascii=False, indent=2))
    return _chat("You produce polished, self-contained HTML slides.", prompt, temperature=0.2, max_tokens=1800 if FAST else 2000)

