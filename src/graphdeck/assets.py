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

# ----------------------------------------------------------------------------- #
# Flags                                                                          #
# ----------------------------------------------------------------------------- #
FAST  = os.getenv("GRAPHDECK_FAST", "0") == "1"
DEBUG = os.getenv("GRAPHDECK_DEBUG", "0") == "1"

# ----------------------------------------------------------------------------- #
# Mermaid templates & helpers                                                    #
# ----------------------------------------------------------------------------- #
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

def _looks_like_mermaid(s: str) -> bool:
    s = (s or "").strip().lower()
    return s.startswith("flowchart") and "td" in s[:40]

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

# ----------------------------------------------------------------------------- #
# FEW-SHOT Mermaid generation from title+bullets (LLM)                           #
# ----------------------------------------------------------------------------- #

FEW_SHOT_MERMAID_SYSTEM = """You convert slide titles and bullets into clean Mermaid flowcharts.

Constraints:
- Flow direction: TD (top→down).
- Label brevity: <= 6 words per node.
- Class styling: use classDef from the example (title, block, warn).
- Parse patterns:
  * 'A -> B -> C' = linear pipeline nodes.
  * 'Heading: a, b, c' = one parent with three children.
  * A question or line starting with 'Decision' creates a diamond (warn).
- Avoid duplicate or overlapping edges; group related bullets.

Return ONLY Mermaid code (no backticks, no commentary)."""

FEW_SHOT_MERMAID_PROMPT = """You are given a slide TITLE and BULLETS. Produce a single Mermaid flowchart (TD) that represents the structure implied by the bullets.

EXAMPLE 1
INPUT:
{
  "title": "Checkout Optimization",
  "bullets": [
    "Identify friction -> Reduce steps -> A/B test",
    "Decision: Offer guest checkout?",
    "KPIs: conversion, drop-off rate"
  ]
}
OUTPUT:
flowchart TD
  classDef title fill:#202a45,stroke:#6b86ff,stroke-width:1px,color:#e8ecff,rx:8,ry:8
  classDef block fill:#121a2b,stroke:#6b86ff,stroke-width:1px,color:#e8ecff,rx:8,ry:8
  classDef warn  fill:#2b2312,stroke:#fbbf24,color:#ffeab6,rx:8,ry:8
  T_Checkout_Optimization["Checkout Optimization"]:::title
  B1_Identify_friction_S0["Identify friction"]:::block
  T_Checkout_Optimization --> B1_Identify_friction_S0
  B1_Identify_friction_S1["Reduce steps"]:::block
  B1_Identify_friction_S0 --> B1_Identify_friction_S1
  B1_Identify_friction_S2["A/B test"]:::block
  B1_Identify_friction_S1 --> B1_Identify_friction_S2
  B2_Decision_Offer_guest_checkout_Q["Decision: Offer guest checkout?"]:::warn
  T_Checkout_Optimization --> B2_Decision_Offer_guest_checkout_Q
  B3_KPIs_S0["KPIs"]:::block
  T_Checkout_Optimization --> B3_KPIs_S0
  B3_KPIs_S1["conversion"]:::block
  B3_KPIs_S0 --> B3_KPIs_S1
  B3_KPIs_S2["drop-off rate"]:::block
  B3_KPIs_S1 --> B3_KPIs_S2

EXAMPLE 2
INPUT:
{
  "title": "Sustainable Retail",
  "bullets": [
    "Materials: organic cotton, recycled PET, hemp",
    "Decision: Local sourcing?",
    "Logistics -> Packaging -> Returns"
  ]
}
OUTPUT:
flowchart TD
  classDef title fill:#202a45,stroke:#6b86ff,stroke-width:1px,color:#e8ecff,rx:8,ry:8
  classDef block fill:#121a2b,stroke:#6b86ff,stroke-width:1px,color:#e8ecff,rx:8,ry:8
  classDef warn  fill:#2b2312,stroke:#fbbf24,color:#ffeab6,rx:8,ry:8
  T_Sustainable_Retail["Sustainable Retail"]:::title
  B1_Materials_H["Materials"]:::block
  T_Sustainable_Retail --> B1_Materials_H
  B1_Materials_I1["organic cotton"]:::block
  B1_Materials_H --> B1_Materials_I1
  B1_Materials_I2["recycled PET"]:::block
  B1_Materials_I1 --> B1_Materials_I2
  B1_Materials_I3["hemp"]:::block
  B1_Materials_I2 --> B1_Materials_I3
  B2_Decision_Local_sourcing_Q["Decision: Local sourcing?"]:::warn
  T_Sustainable_Retail --> B2_Decision_Local_sourcing_Q
  B3_Logistics_S0["Logistics"]:::block
  T_Sustainable_Retail --> B3_Logistics_S0
  B3_Logistics_S1["Packaging"]:::block
  B3_Logistics_S0 --> B3_Logistics_S1
  B3_Logistics_S2["Returns"]:::block
  B3_Logistics_S1 --> B3_Logistics_S2

NOW DO THE SAME FOR THIS INPUT:
{
  "title": %(title_json)s,
  "bullets": %(bullets_json)s
}
"""

def mermaid_from_title_bullets_llm(title: str, bullets: List[str]) -> str:
    """
    Few-shot LLM conversion from slide title+bullets to Mermaid.
    Falls back to deterministic builder if output isn't valid Mermaid.
    """
    try:
        prompt = FEW_SHOT_MERMAID_PROMPT % {
            "title_json": json.dumps((title or "").strip()),
            "bullets_json": json.dumps([str(b).strip() for b in (bullets or [])]),
        }
        out = _chat(
            FEW_SHOT_MERMAID_SYSTEM,
            prompt,
            temperature=0.2 if FAST else 0.3,
            max_tokens=700 if FAST else 900,
            prefer="groq",   # prefer Groq when available
        )
        if isinstance(out, str) and _looks_like_mermaid(out):
            return out.strip()
    except Exception as e:
        if DEBUG:
            import traceback; print("mermaid_from_title_bullets_llm error:", e); traceback.print_exc()
    # deterministic fallback
    return build_mermaid_from_title_bullets(title, bullets)

# ----------------------------------------------------------------------------- #
# Rendering                                                                      #
# ----------------------------------------------------------------------------- #
async def _render_html_async(html: str, out_img: str, width: int = 1600, height: int = 900, selector: str = "body") -> None:
    try:
        from playwright.async_api import async_playwright
    except Exception:
        html_path = pathlib.Path(out_img).with_suffix(".html")
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html, encoding="utf-8")
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
                if el: await el.screenshot(path=str(out_path))
                else:  await page.screenshot(path=str(out_path), full_page=False)
        finally:
            await browser.close()

def render_html_to_image(html: str, out_img: str, width: int = 1600, height: int = 900, selector: str = "body") -> None:
    try:
        asyncio.get_running_loop()
        asyncio.run(_render_html_async(html, out_img, width, height, selector))
    except RuntimeError:
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

# ----------------------------------------------------------------------------- #
# Public API used by CLI/content (slide-index stays 3 by default upstream)       #
# ----------------------------------------------------------------------------- #
def flowchart_from_title_bullets(
    title: str,
    bullets: List[str],
    out_path: str,
    *,
    research: Optional[Dict[str, Any]] = None,  # ignored for LLM prompt; kept for compatibility
    use_llm: bool = True,
    width: int = 1200,
    height: int = 800,
) -> str:
    """
    Build a flowchart for a single slide (e.g., slide 3). If LLM is enabled,
    use the few-shot prompt; otherwise deterministic builder.
    """
    if FAST:
        use_llm = False

    if use_llm:
        mmd = mermaid_from_title_bullets_llm(title, bullets)
    else:
        mmd = build_mermaid_from_title_bullets(title, bullets)

    if not _looks_like_mermaid(mmd):
        # last-resort guard
        mmd = build_mermaid_from_title_bullets(title, bullets)

    render_mermaid(mmd, out_path, width=width, height=height)
    return out_path
