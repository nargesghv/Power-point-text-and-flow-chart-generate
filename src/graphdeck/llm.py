from __future__ import annotations

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=False)

import os
import json
import re
from typing import Any, Dict, List, Optional

from .config import settings

# --------------------------------------------------------------------------------------
# Backend toggles
# --------------------------------------------------------------------------------------
# Standardize flags across the codebase:
# - FAST: enable shorter prompts / lower token budgets when "1"
# - NO_LLM: force deterministic fallbacks when "1"
# - DEBUG: print backend exceptions (Groq/Ollama) when "1"
FAST = os.getenv("GRAPHDECK_FAST", "0") == "1"
NO_LLM = os.getenv("GRAPHDECK_NO_LLM", "0") == "1"
DEBUG = os.getenv("GRAPHDECK_DEBUG", "0") == "1"

# --------------------------------------------------------------------------------------
# LLM backends
# --------------------------------------------------------------------------------------
def _try_groq():
    try:
        from groq import Groq
        api_key = os.getenv("GROQ_API_KEY", settings.GROQ_API_KEY)
        if api_key:
            return Groq(api_key=api_key), "groq"
    except Exception as e:
        if DEBUG:
            import traceback; print("GROQ init error:", e); traceback.print_exc()
    return None, None

def _try_ollama():
    try:
        import ollama  # client is the module itself
        base = os.getenv("OLLAMA_BASE_URL") or settings.OLLAMA_BASE_URL
        if base:
            os.environ["OLLAMA_HOST"] = base
        return ollama, "ollama"
    except Exception as e:
        if DEBUG:
            import traceback; print("OLLAMA init error:", e); traceback.print_exc()
    return None, None

def _extract_json(text: str) -> str:
    """Pull the first {...} blob when models wrap JSON with prose."""
    m1 = text.find("{")
    m2 = text.rfind("}")
    if m1 != -1 and m2 != -1 and m2 > m1:
        return text[m1:m2+1]
    return text

def _chat(
    system: str,
    user: str,
    temperature: float = 0.3,
    max_tokens: int = 1200,
    force_json: bool = False,
    prefer: str | None = None,
) -> str:
    """
    Chat with an LLM. Prefer 'groq' for quality and 'ollama' as fallback unless overridden.
    """
    # Preferred order
    order = ["groq", "ollama"]
    if prefer == "ollama":
        order = ["ollama", "groq"]
    elif prefer == "groq":
        order = ["groq", "ollama"]

    def try_groq():
        client, which = _try_groq()
        if which != "groq":
            return None
        try:
            resp = client.chat.completions.create(
                model=os.getenv("GROQ_MODEL", settings.GROQ_MODEL),
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            out = resp.choices[0].message.content or ""
            return _extract_json(out) if force_json else out
        except Exception as e:
            if DEBUG:
                import traceback; print("GROQ error:", e); traceback.print_exc()
            return None

    def try_ollama():
        ol, which = _try_ollama()
        if which != "ollama":
            return None
        try:
            resp = ol.chat(
                model=os.getenv("OLLAMA_MODEL", settings.OLLAMA_MODEL),
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": user}],
                options={"temperature": temperature},
            )
            out = (resp or {}).get("message", {}).get("content", "") or ""
            return _extract_json(out) if force_json else out
        except Exception as e:
            if DEBUG:
                import traceback; print("OLLAMA error:", e); traceback.print_exc()
            return None

    for backend in order:
        out = try_groq() if backend == "groq" else try_ollama()
        if out:
            return out

    raise RuntimeError("No working LLM backend. Configure GROQ_API_KEY, or start Ollama and pull the model.")

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def shorten_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        d = urlparse(url).netloc.lower()
        return d[4:] if d.startswith("www.") else d
    except Exception:
        return url

def build_source_table(sources: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    table: List[Dict[str, str]] = []
    for idx, s in enumerate(sources, 1):
        u = s.get("url") or ""
        table.append({
            "id": str(idx),
            "title": (s.get("title") or "")[:120],
            "url": u,
            "domain": shorten_domain(u),
        })
    return table

# --------------------------------------------------------------------------------------
# Prompts
# --------------------------------------------------------------------------------------
SUMMARIZE_PROMPT = """You are a careful researcher. Write a concise, multi-paragraph summary of the TOPIC using the SOURCES table.
- Keep it tight, fact-focused, and practical for a small-business audience.
- Cite inline like [1], [2] using the id column when you borrow a claim.
- End with 3–5 specific, fast-ROI recommendations.
INPUT (JSON):
{input_json}
"""

BLOG_PROMPT = """You are a professional content writer. Create a comprehensive blog post about the TOPIC that tells a complete story.

Use this RESEARCH SUMMARY as grounding context (if any):
---
{research_context}
---

The blog should:
- Start with an engaging introduction that hooks the reader
- Develop key concepts progressively and connect ideas logically
- End with actionable insights and conclusions
- Be 800–1200 words total{length_hint}
- Use a storytelling approach with clear headings (Markdown)

TOPIC: {topic}
"""

OUTLINE_PROMPT = """Design a PowerPoint slide outline based on the BLOG content. Return STRICT JSON ONLY with keys:
- "slide_count" (int, 6–8)
- "sections" (array of {{"title": str, "bullets": [str]}})

Requirements:
- Slide 1 title MUST be exactly the topic and have no bullets
- Total slides: 6 (exact)
- Each slide title must be concise, professional
- Slides must follow a logical storytelling flow from the blog
- Keep bullets concise (max 5 per slide, max 14 words per bullet)

BLOG CONTENT:
{blog_content}

INPUT (JSON):
{input_json}
"""

# --------------------------------------------------------------------------------------
# Summarization API (legacy; still useful in some flows)
# --------------------------------------------------------------------------------------
def summarize_with_citations(topic: str, sources: List[Dict[str, Any]]) -> str:
    table = build_source_table(sources)[:10]
    payload = {"topic": topic, "sources": table}
    prompt = SUMMARIZE_PROMPT.format(input_json=json.dumps(payload, ensure_ascii=False, indent=2))
    return _chat(
        "You craft precise, cited summaries.",
        prompt,
        temperature=0.2 if FAST else 0.3,
        max_tokens=900 if FAST else 1200,
        prefer="groq",  # prefer Groq for quality
    )

# --------------------------------------------------------------------------------------
# Blog generation (prefers Groq; robust fallback)
# --------------------------------------------------------------------------------------
def _fallback_blog_from_summary(topic: str, research: Optional[Dict[str, Any]]) -> str:
    summary = (research or {}).get("summary") or ""
    lines = [f"# {topic}", ""]
    if summary.strip():
        lines += [
            "## Executive Summary",
            *[ln for ln in (summary.splitlines()) if ln.strip().startswith("- ")][:5],
            "",
            "## Landscape",
            "- Current state & drivers",
            "- Data/tooling prerequisites",
            "- Metrics that matter",
            "",
            "## Opportunities",
            "- Quick wins (< 90 days)",
            "- Medium bets (quarterly)",
            "- Longer bets (platform/ops)",
            "",
            "## Risks & Governance",
            "- Quality, safety, privacy",
            "- Human-in-the-loop checks",
            "- Change management & training",
            "",
            "## Getting Started",
            "- Pick one pilot and KPI",
            "- Baseline, iterate weekly",
            "- Document wins to scale",
        ]
    else:
        lines += [
            "## Overview",
            "This primer outlines value, use cases, and a phased rollout plan.",
            "",
            "## Core Concepts",
            "- Where AI helps most",
            "- Data readiness",
            "- Guardrails",
            "",
            "## Applications",
            "- Quick wins",
            "- Medium bets",
            "- Long bets",
            "",
            "## Rollout",
            "- Pilot → KPI → Iterate",
            "- Enable team",
            "- Scale",
        ]
    return "\n".join(lines)

def generate_blog(
    topic: str,
    *,
    research: Optional[Dict[str, Any]] = None,
    max_tokens: int = 1200,
    temperature: float = 0.4,
    prefer: str | None = None,
) -> str:
    """
    Generate a comprehensive blog post about the topic.
    Uses research['summary'] as grounding context when available.
    Prefers Groq; falls back to Ollama; deterministic fallback if models fail.
    """
    if NO_LLM:
        return _fallback_blog_from_summary(topic, research)

    # Ground with research summary (trim length based on FAST mode)
    research_context = ""
    if research:
        summary = (research.get("summary") or "").strip()
        if summary:
            research_context = summary[:700 if FAST else 1200]

    length_hint = " (or 350–500 words in fast mode)" if FAST else ""
    prompt = BLOG_PROMPT.format(
        topic=topic,
        research_context=research_context or "(none provided)",
        length_hint=length_hint,
    )
    try:
        out = _chat(
            "You are a professional content writer who creates engaging, well-structured blog posts.",
            prompt,
            temperature=0.2 if FAST else temperature,
            max_tokens=550 if FAST else max_tokens,
            prefer=prefer or "groq",
        )
        if isinstance(out, str) and len(out.strip()) > 200:
            return out
    except Exception as e:
        if DEBUG:
            import traceback; print("generate_blog error:", e); traceback.print_exc()
    return _fallback_blog_from_summary(topic, research)

# --------------------------------------------------------------------------------------
# Outline generation (prefers Groq; robust fallback)
# --------------------------------------------------------------------------------------
def _outline_from_blog_or_summary(topic: str, blog_content: str) -> Dict[str, Any]:
    """
    Build a clean 6-slide outline from headings/bullets in blog_content.
    Slide 1 = exact topic (no bullets). If headings missing, produce defaults.
    """
    slides = [{"title": topic, "bullets": []}]  # Slide 1

    # Extract H2s (## ) as candidate slide titles and bullets under them
    h2 = [m.strip("# ").strip() for m in re.findall(r"(?m)^## +.+$", blog_content or "")]
    parts = re.split(r"(?m)^## +.+$", blog_content)[1:] if h2 else []
    sections: List[Dict[str, Any]] = []
    if h2 and parts:
        for title, block in zip(h2, parts):
            if title.lower().strip() in {"executive summary"}:
                continue
            bullets: List[str] = []
            for b in re.findall(r"(?m)^[\-\*]\s+(.+)$", block):
                b = re.sub(r"\s+", " ", b).strip()
                if b:
                    bullets.append(b[:120])
                if len(bullets) >= 5:
                    break
            if title:
                sections.append({"title": title[:70], "bullets": bullets[:5]})

    # Defaults to ensure 5 content slides after title
    defaults = [
        {"title":"Context & Opportunity","bullets":["Why now","Where value concentrates","Impact on CX & ops"]},
        {"title":"Core Concepts","bullets":["Key idea 1","Key idea 2","Key idea 3"]},
        {"title":"Process / Flow","bullets":["Step 1 → Step 2 → Step 3","Decision points","Metrics: quality, speed, cost"]},
        {"title":"Use Cases","bullets":["Quick wins","Medium bets","Long bets"]},
        {"title":"Next Steps","bullets":["Pick pilot + KPI","Baseline & iterate","Scale what works"]},
    ]
    pool = sections or defaults
    for s in pool:
        if len(slides) >= 6:
            break
        slides.append({"title": s["title"][:70], "bullets": [b[:120] for b in (s.get("bullets") or [])][:5]})
    while len(slides) < 6:
        d = defaults[len(slides)-1]
        slides.append({"title": d["title"], "bullets": d["bullets"]})
    return {"slide_count": 6, "sections": slides[:6]}

def make_outline(
    topic: str,
    blog_content: str,
    audience: str = "executive & technical mixed",
    tone: str = "crisp and practical",
    *,
    max_tokens: int = 700,
    temperature: float = 0.3,
    prefer: str | None = None,
) -> Dict[str, Any]:
    """
    Ask LLM for JSON outline. If parsing fails or output is weak, derive deterministically.
    Always returns 6 slides with Slide 1 = topic (no bullets).
    """
    if NO_LLM:
        return _outline_from_blog_or_summary(topic, blog_content)

    payload = {"topic": topic, "audience": audience, "tone": tone}
    prompt = OUTLINE_PROMPT.format(
        blog_content=blog_content,
        input_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    try:
        raw = _chat(
            "You design cohesive 6-slide outlines that tell a story.",
            prompt,
            temperature=0.25 if FAST else temperature,
            max_tokens=450 if FAST else max_tokens,
            force_json=True,
            prefer=prefer or "groq",
        )
        data = json.loads(raw)
        sections = data.get("sections") or []
        # Normalize slide 1
        if sections:
            sections[0]["title"] = topic
            sections[0]["bullets"] = []
        # Enforce 6 slides
        if len(sections) != 6:
            return _outline_from_blog_or_summary(topic, blog_content)
        # Trim & sanitize
        for i, s in enumerate(sections):
            s["title"] = (s.get("title") or "").strip()[:70]
            s["bullets"] = ([] if i == 0 else [b.strip()[:120] for b in (s.get("bullets") or [])][:5])
        return {"slide_count": 6, "sections": sections}
    except Exception as e:
        if DEBUG:
            import traceback; print("make_outline error:", e); traceback.print_exc()
        return _outline_from_blog_or_summary(topic, blog_content)

