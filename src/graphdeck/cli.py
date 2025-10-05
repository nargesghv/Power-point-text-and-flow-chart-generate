from __future__ import annotations

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=False)  # load .env before any env access

import json
import os
from typing import List, Optional
import typer

from .utils import slugify, ensure_dir

app = typer.Typer(help="graphdeck: research → synthesize → outline → content (+ slide 3 flowchart)")

# ---------- Research ----------

@app.command()
def research(
    topic: str,
    max_sources: int = typer.Option(12, help="Max web sources"),
    max_images: int = typer.Option(6, help="Max images"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    if fast:
        os.environ["GRAPHDECK_FAST"] = "1"
    from .research import research_topic

    typer.echo(f"🔎 Researching: {topic}")
    bundle = research_topic(topic=topic, max_sources=max_sources, max_images=max_images)
    ensure_dir(out_dir)
    slug = slugify(topic)
    out_json = os.path.join(out_dir, f"research_{slug}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(bundle, f, ensure_ascii=False, indent=2)
    typer.echo(f"✅ Saved research to {out_json}")

# ---------- Synthesize (SUMMARY) ----------

@app.command()
def synthesize(
    research_json: str = typer.Argument(..., help="research_*.json"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    """Create a concise, cited summary and embed it back into the research JSON."""
    if fast:
        os.environ["GRAPHDECK_FAST"] = "1"
    # supports either file name: summarize.py or summerize.py
    try:
        from .summarize import synthesize_bundle  # preferred
    except ImportError:
        from .summerize import synthesize_bundle  # legacy filename

    assert os.path.exists(research_json), f"Missing: {research_json}"
    bundle = json.load(open(research_json, "r", encoding="utf-8"))
    topic = bundle.get("topic") or "topic"

    ensure_dir(out_dir)
    slug = slugify(topic)

    # add "summary" to bundle
    out = synthesize_bundle(bundle)

    # write summary md
    summary_md = os.path.join(out_dir, f"summary_{slug}.md")
    with open(summary_md, "w", encoding="utf-8") as f:
        f.write(out.get("summary") or "")

    # overwrite research json with embedded summary
    with open(research_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    typer.echo(f"✅ Summary written → {summary_md} and embedded into {research_json}")

# ---------- Blog (optional; generate from summary/research if present) ----------

@app.command()
def blog(
    topic: str,
    research_json: str = typer.Option("", "--research-json"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    if fast:
        os.environ["GRAPHDECK_FAST"] = "1"
    from .llm import generate_blog

    ensure_dir(out_dir)
    slug = slugify(topic)

    research = None
    if research_json and os.path.exists(research_json):
        research = json.load(open(research_json, "r", encoding="utf-8"))

    content = generate_blog(topic, research=research)  # uses research["summary"] if available
    path = os.path.join(out_dir, f"blog_{slug}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    typer.echo(f"✅ Wrote blog → {path}")

# ---------- Outline (BLOG-ONLY) ----------

@app.command()
def outline(
    topic: str,
    blog_md: str = typer.Option("", "--blog-md", help="Path to Blog markdown (.md). If omitted, will generate from research."),
    research_json: str = typer.Option("", "--research-json", help="Research JSON (should include 'summary' for better blog generation)"),
    audience: str = typer.Option("executive & technical mixed"),
    tone: str = typer.Option("crisp and practical"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    """
    Build a 6-slide outline **from the blog markdown only**.
    If --blog-md isn't provided, we generate the blog first (from research if present).
    """
    if fast:
        os.environ["GRAPHDECK_FAST"] = "1"
    from .llm import make_outline, generate_blog

    ensure_dir(out_dir)
    slug = slugify(topic)

    # 1) Get the blog markdown (either provided or generated)
    if blog_md and os.path.exists(blog_md):
        blog_content = open(blog_md, "r", encoding="utf-8").read()
    else:
        research = None
        if research_json and os.path.exists(research_json):
            research = json.load(open(research_json, "r", encoding="utf-8"))
        else:
            auto = os.path.join(out_dir, f"research_{slug}.json")
            if os.path.exists(auto):
                research = json.load(open(auto, "r", encoding="utf-8"))
        blog_content = generate_blog(topic, research=research)

    # 2) Save the blog to keep artifacts consistent
    blog_path = os.path.join(out_dir, f"blog_{slug}.md")
    with open(blog_path, "w", encoding="utf-8") as f:
        f.write(blog_content)

    # 3) Make outline strictly from the blog (no summary preference)
    plan = make_outline(topic=topic, blog_content=blog_content, audience=audience, tone=tone)

    out_json = os.path.join(out_dir, f"outline_{slug}.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    typer.echo(f"✅ Wrote outline → {out_json} (slides: {plan.get('slide_count', 'n/a')})")

# ---------- Flowchart from a slide (STRICTLY from outline title+bullets) ----------

@app.command()
def slidechart(
    outline_json: str = typer.Option(..., help="Path to outline_*.json with sections"),
    slide_index: int = typer.Option(3, help="1-based slide index to chart (default: 3)"),
    out_png: str = typer.Option("out/slide_flowchart.png"),
    # keep flags for backward-compat, but we ignore research and quick_research now
    research_json: str = typer.Option("", help="(ignored)"),
    quick_research: bool = typer.Option(False, help="(ignored)"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Use deterministic chart builder (no LLM)"),
    width: int = typer.Option(1200),
    height: int = typer.Option(800),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    """
    Render ONE slide's flowchart using ONLY that slide's title and bullets from the outline.
    No research. No summary. Exact alignment with slides text.
    """
    if fast:
        os.environ["GRAPHDECK_FAST"] = "1"

    from .assets import flowchart_from_title_bullets

    assert os.path.exists(outline_json), f"Missing file: {outline_json}"
    outline = json.load(open(outline_json, "r", encoding="utf-8"))
    sections = outline.get("sections") or []
    idx = max(1, slide_index) - 1
    assert 0 <= idx < len(sections), f"slide_index {slide_index} out of range (1..{len(sections)})"

    slide = sections[idx]
    title = slide.get("title") or f"Slide {slide_index}"
    bullets = [b for b in (slide.get("bullets") or []) if str(b).strip()]

    ensure_dir(os.path.dirname(out_png) or ".")
    flowchart_from_title_bullets(
        title=title,
        bullets=bullets,
        out_path=out_png,
        research=None,                 # strictly from slide content
        use_llm=(not no_llm),          # optional LLM formatting; still bound to given bullets
        width=width,
        height=height,
    )
    typer.echo(f"✅ Wrote {out_png}")

# ---------- Content (text + slide-3 flowchart) ----------

@app.command()
def content(
    topic: str,
    outline_json: str = typer.Option("", "--outline-json"),
    research_json: str = typer.Option("", "--research-json"),
    visual_path: str = typer.Option("", "--visual-path"),
    mermaid_pngs: Optional[List[str]] = typer.Option(None, "--mermaid-png"),
    out_dir: str = typer.Option("out", help="Directory to write outputs"),
    chart_from_slide: bool = typer.Option(True, help="Also generate a flowchart from a slide's title+bullets"),
    chart_slide_index: int = typer.Option(3, help="Which slide (1-based) to chart"),
    chart_width: int = typer.Option(1200),
    chart_height: int = typer.Option(800),
    chart_no_llm: bool = typer.Option(False, "--chart-no-llm"),
    fast: bool = typer.Option(False, "--fast", help="Enable fast mode"),
):
    if fast:
        os.environ["GRAPHDECK_FAST"] = "1"
    from .ppt import generate_powerpoint_content
    from .assets import flowchart_from_title_bullets
    # from .research import research_topic  # no longer needed here

    ensure_dir(out_dir)
    slug = slugify(topic)

    outline = json.load(open(outline_json, "r", encoding="utf-8")) if outline_json and os.path.exists(outline_json) else None
    research = json.load(open(research_json, "r", encoding="utf-8")) if research_json and os.path.exists(research_json) else None

    mm_paths = list(mermaid_pngs or [])

    # Make a flowchart from a single slide (defaults to slide 3) — strictly from the slide text
    if chart_from_slide and outline and isinstance(outline.get("sections"), list):
        idx = max(1, chart_slide_index) - 1
        if 0 <= idx < len(outline["sections"]):
            sec = outline["sections"][idx]
            title = sec.get("title") or f"Slide {chart_slide_index}"
            bullets = [b for b in (sec.get("bullets") or []) if str(b).strip()]
            slide_png = os.path.join(out_dir, f"diagram_{slug}_slide{chart_slide_index}.png")
            flowchart_from_title_bullets(
                title=title,
                bullets=bullets,
                out_path=slide_png,
                research=None,              # strictly from slide content
                use_llm=(not chart_no_llm), # optional LLM formatting
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

if __name__ == "__main__":
    app()


