from __future__ import annotations
import os, json
from typing import Dict, Any, List, Optional

from .utils import ensure_dir

TEXT_NAME = "slides_text_{slug}.txt"

def _format_slide_text(topic: str, outline: Dict[str, Any]) -> str:
    """
    Produce the exact text format requested:
    Title: <topic>

    Slide: <title>
    • bullet
    • bullet
    """
    sections: List[Dict[str, Any]] = outline.get("sections") or []
    # Force slide 1 shape: exact topic, no bullets
    if not sections:
        sections = [{"title": topic, "bullets": []}]
    else:
        sections[0]["title"] = topic
        sections[0]["bullets"] = []

    lines: List[str] = []
    lines.append(f"Title: {topic}")
    lines.append("")  # blank line

    for i, sec in enumerate(sections[1:6], start=2):  # Slides 2..6
        title = sec.get("title") or f"Slide {i}"
        bullets = [b for b in (sec.get("bullets") or []) if str(b).strip()]
        lines.append(f"Slide: {title}")
        for b in bullets:
            lines.append(f"• {b.strip()}")
        lines.append("")  # blank line between slides

    return "\n".join(lines).rstrip() + "\n"

def generate_powerpoint_content(
    topic: str,
    outline: Optional[Dict[str, Any]],
    research: Optional[Dict[str, Any]],
    visual_path: Optional[str],
    mermaid_paths: List[str],
    out_dir: str,
    slug: str,
) -> Dict[str, str]:
    """
    Writes a single text file in the exact format demanded + returns paths of assets.
    """
    ensure_dir(out_dir)
    if not outline:
        outline = {"sections": [{"title": topic, "bullets": []}]}

    text_body = _format_slide_text(topic, outline)
    text_path = os.path.join(out_dir, TEXT_NAME.format(slug=slug))
    with open(text_path, "w", encoding="utf-8") as f:
        f.write(text_body)

    out: Dict[str, str] = {"text": text_path}

    # include optional assets if present
    if visual_path and os.path.exists(visual_path):
        out["visual"] = visual_path

    # copy mermaid/flowchart images (already rendered); just list them
    for i, p in enumerate(mermaid_paths or [], start=1):
        if os.path.exists(p):
            out[f"diagram_{i}"] = p

    # materialize outline + research as references (handy for debugging)
    outline_json = os.path.join(out_dir, f"outline_{slug}.json")
    with open(outline_json, "w", encoding="utf-8") as f:
        json.dump(outline, f, ensure_ascii=False, indent=2)
    out["outline_json"] = outline_json

    if research:
        research_json = os.path.join(out_dir, f"research_{slug}.json")
        with open(research_json, "w", encoding="utf-8") as f:
            json.dump(research, f, ensure_ascii=False, indent=2)
        out["research_json"] = research_json

    return out
