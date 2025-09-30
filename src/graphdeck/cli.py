from __future__ import annotations
import json
import os
import typer
from typing import List, Optional

from .utils import slugify, ensure_dir

app = typer.Typer(help="graphdeck: research → summarize → blog → outline → content (flowchart from slide bullets only)")

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _enable_fast(fast: bool):
    if fast:
        os.environ["GRAPHDECK_FAST"] = "1"

def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def _write_json(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ──────────────────────────────────────────────────────────────────────────────
# research
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def research(
    topic: str,
    max_sources: int = typer.Option(12, help="Max web sources"),
    max_images: int = typer.Option(6, help="Max images"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    """
    Run web research and write research_<slug>.json (optionally with downloaded images).
    """
    _enable_fast(fast)
    from .research import research_topic

    typer.echo(f"🔎 Researching: {topic}")
    bundle = research_topic(topic=topic, max_sources=max_sources, max_images=max_images)

    ensure_dir(out_dir)
    slug = slugify(topic)
    out_json = os.path.join(out_dir, f"research_{slug}.json")
    _write_json(out_json, bundle)
    typer.echo(f"✅ Saved research → {out_json}")

# ──────────────────────────────────────────────────────────────────────────────
# synthesize (creates summary markdown + embeds it back into research json)
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def synthesize(
    research_json: str = typer.Argument(..., help="Path to research_*.json"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode (shorter output)"),
):
    """
    Create a concise, cited summary and embed it back into the same research JSON.
    Also writes summary_<slug>.md for convenience.
    """
    _enable_fast(fast)

    # Support summarize.py (preferred) OR summerize.py (legacy)
    try:
        from .summarize import synthesize_bundle  # preferred
    except Exception:
        from .summerize import synthesize_bundle  # legacy filename

    assert os.path.exists(research_json), f"Missing: {research_json}"
    bundle = _load_json(research_json)
    topic = bundle.get("topic") or "topic"

    ensure_dir(out_dir)
    slug = slugify(topic)

    out_bundle = synthesize_bundle(bundle)  # adds 'summary' field
    _write_json(research_json, out_bundle)

    summary_md = os.path.join(out_dir, f"summary_{slug}.md")
    with open(summary_md, "w", encoding="utf-8") as f:
        f.write(out_bundle.get("summary") or "")

    typer.echo(f"✅ Summary written → {summary_md} and embedded into {research_json}")

# ──────────────────────────────────────────────────────────────────────────────
# blog (structured: Introduction → Main → Conclusion)
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def blog(
    topic: str,
    research_json: str = typer.Option("", "--research-json", help="Optional research bundle (uses embedded summary if present)"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    """
    Generate a blog post grounded by the research summary (if present) with the sections:
    # <topic>, ## Introduction, ## Main, ## Conclusion
    """
    _enable_fast(fast)
    from .llm import generate_blog

    ensure_dir(out_dir)
    slug = slugify(topic)
    research = _load_json(research_json) if research_json and os.path.exists(research_json) else None

    content = generate_blog(topic, research=research)
    path = os.path.join(out_dir, f"blog_{slug}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

    typer.echo(f"✅ Wrote blog → {path}")

# ──────────────────────────────────────────────────────────────────────────────
# outline (6 slides; Slide 1 = topic; Slide 6 = conclusion)
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def outline(
    topic: str,
    blog_md: str = typer.Option("", "--blog-md", help="Optional blog markdown file; if omitted we generate from research"),
    research_json: str = typer.Option("", "--research-json", help="Research JSON (should include 'summary')"),
    audience: str = typer.Option("executive & technical mixed"),
    tone: str = typer.Option("crisp and practical"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    """
    Produce outline_<slug>.json: 6 slides (Slide 1 title = topic, no bullets; 2..5 body; 6 conclusion).
    """
    _enable_fast(fast)
    from .llm import make_outline, generate_blog

    ensure_dir(out_dir)
    slug = slugify(topic)

    # Get blog content
    if blog_md and os.path.exists(blog_md):
        blog_content = open(blog_md, "r", encoding="utf-8").read()
    else:
        research = None
        if research_json and os.path.exists(research_json):
            research = _load_json(research_json)
        else:
            auto = os.path.join(out_dir, f"research_{slug}.json")
            if os.path.exists(auto):
                research = _load_json(auto)
        blog_content = generate_blog(topic, research=research)

    plan = make_outline(topic=topic, blog_content=blog_content, audience=audience, tone=tone)
    out_json = os.path.join(out_dir, f"outline_{slug}.json")
    _write_json(out_json, plan)
    typer.echo(f"✅ Wrote outline → {out_json} (slides: {plan.get('slide_count', 'n/a')})")

# ──────────────────────────────────────────────────────────────────────────────
# slidechart (flowchart from one slide's title + bullets ONLY; no research; no LLM)
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def slidechart(
    outline_json: str = typer.Option(..., help="Path to outline_*.json with sections"),
    slide_index: int = typer.Option(3, help="1-based slide index to chart"),
    out_png: str = typer.Option("out/slide_flowchart.png"),
    width: int = typer.Option(1200),
    height: int = typer.Option(800),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode (no effect here)"),
):
    """
    Render a flowchart strictly from the chosen slide's title+bullets (deterministic).
    No web research. No LLM.
    """
    _enable_fast(fast)
    from .assets import flowchart_from_title_bullets

    assert os.path.exists(outline_json), f"Missing file: {outline_json}"
    outline = _load_json(outline_json)
    sections = outline.get("sections") or []

    idx = max(1, slide_index) - 1
    assert 0 <= idx < len(sections), f"slide_index {slide_index} out of range (1..{len(sections)})"

    slide = sections[idx]
    title = slide.get("title") or f"Slide {slide_index}"
    bullets = slide.get("bullets") or []

    ensure_dir(os.path.dirname(out_png) or ".")
    flowchart_from_title_bullets(
        title=title,
        bullets=bullets,
        out_path=out_png,
        research=None,
        use_llm=False,      # ← enforce deterministic charting from bullets only
        width=width,
        height=height,
    )
    typer.echo(f"✅ Wrote {out_png}")

# ──────────────────────────────────────────────────────────────────────────────
# content (slides text + flowchart from one slide; NO research; NO LLM)
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def content(
    topic: str,
    outline_json: str = typer.Option("", "--outline-json"),
    research_json: str = typer.Option("", "--research-json"),
    visual_path: str = typer.Option("", "--visual-path"),
    mermaid_pngs: List[str] = typer.Option(None, "--mermaid-png"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    chart_from_slide: bool = typer.Option(True, help="Generate a flowchart from a slide's title+bullets"),
    chart_slide_index: int = typer.Option(3, help="Which slide (1-based) to chart"),
    chart_width: int = typer.Option(1200),
    chart_height: int = typer.Option(800),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    """
    Generate the slides text file and (optionally) a flowchart image derived only from the chosen slide.
    """
    _enable_fast(fast)
    from .ppt import generate_powerpoint_content
    from .assets import flowchart_from_title_bullets

    ensure_dir(out_dir)
    slug = slugify(topic)

    outline = _load_json(outline_json) if outline_json and os.path.exists(outline_json) else None
    research = _load_json(research_json) if research_json and os.path.exists(research_json) else None

    mm_paths = list(mermaid_pngs or [])

    # Deterministic flowchart from slide bullets (no LLM, no research)
    if chart_from_slide and outline and isinstance(outline.get("sections"), list):
        idx = max(1, chart_slide_index) - 1
        if 0 <= idx < len(outline["sections"]):
            sec = outline["sections"][idx]
            title = sec.get("title") or f"Slide {chart_slide_index}"
            bullets = sec.get("bullets") or []
            slide_png = os.path.join(out_dir, f"diagram_{slug}_slide{chart_slide_index}.png")

            flowchart_from_title_bullets(
                title=title,
                bullets=bullets,
                out_path=slide_png,
                research=None,
                use_llm=False,     # ← enforce deterministic
                width=chart_width,
                height=chart_height,
            )
            mm_paths.append(slide_png)

    content_files = generate_powerpoint_content(
        topic=topic,
        outline=outline,
        research=research,
        visual_path=(visual_path or None),
        mermaid_paths=mm_paths,
        out_dir=out_dir,
        slug=slug,
    )

    typer.echo("✅ Generated PowerPoint content:")
    for kind, path in (content_files or {}).items():
        typer.echo(f"  {kind}: {path}")

# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app()

