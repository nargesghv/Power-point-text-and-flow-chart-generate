from __future__ import annotations
import json, os
from typing import Any, Dict, List, Optional

from .llm import _chat, build_source_table

FAST = os.getenv("GRAPHDECK_FAST") == "1"

SUMMARY_PROMPT_V2 = """You are a senior industry analyst. Given a TOPIC and a SOURCES table, write a concise,
decision-ready brief in Markdown that an executive can scan in < 2 minutes.

OUTPUT STRUCTURE (exactly these sections):
# {topic}
## Executive Summary
- 3–5 bullets, plain language, the “so what”
## Landscape
- 3–5 bullets on what’s happening now
## Opportunities
- 3–5 bullets with concrete opportunity areas
## Risks & Constraints
- 3–5 bullets on risks, pitfalls, constraints
## Quick Wins (<= 90 days)
- 3–5 bullets with actions, each with a clear KPI

CITATIONS:
- When a claim is drawn from a source, add inline [id] where id is the row from SOURCES.
- Don’t put raw URLs in the bullets, only [id] markers.
- It’s OK if not every bullet has a citation.

STYLE:
- Crisp, neutral tone. No fluff. Max ~120 words per section (Fast mode: ~70).
- No headings besides the ones listed above.
- No intro/outro prose outside the sections.

EXAMPLE
INPUT_JSON:
{{
  "topic": "AI in Retail Sales",
  "sources": [
    {{"id":"1","title":"AI boosts conversion by personalization","url":"https://example.com/a","domain":"example.com"}},
    {{"id":"2","title":"Computer vision for shelf analytics","url":"https://example.com/b","domain":"example.com"}}
  ]
}}
OUTPUT_MARKDOWN:
# AI in Retail Sales
## Executive Summary
- Retailers use AI to increase conversion via personalization and timing [1].
- Vision models improve on-shelf availability and reduce stockouts [2].
- Early wins cluster around search, recommendations, and assisted selling.
## Landscape
- First-party data quality is the bottleneck; CDPs and consent matter.
- …
## Opportunities
- …
## Risks & Constraints
- …
## Quick Wins (<= 90 days)
- …

NOW WRITE THE BRIEF FOR THE REAL INPUT BELOW.
INPUT_JSON:
{input_json}
"""

def write_summary_markdown(topic: str, sources: List[Dict[str, Any]]) -> str:
    table = build_source_table(sources)[:10]
    payload = {"topic": topic, "sources": table}
    prompt = SUMMARY_PROMPT_V2.format(
        topic=topic,
        input_json=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    # Smaller models behave better with lower temperature + tighter tokens
    temperature = 0.2 if FAST else 0.3
    max_tokens = 600 if FAST else 1100
    out = _chat(
        "You write concise, decision-ready executive briefs with inline [id] citations.",
        prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        force_json=False,
        prefer="ollama",  # favor local model to avoid API delays
    )
    return out if isinstance(out, str) else ""

def synthesize_bundle(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Take a research bundle { topic, sources, images? } and add a 'summary' (markdown).
    Always returns a bundle with a non-empty 'summary' (falls back to a tiny deterministic one if needed).
    """
    topic = bundle.get("topic", "").strip() or "Topic"
    sources = bundle.get("sources", []) or []
    summary_md = ""

    try:
        summary_md = write_summary_markdown(topic, sources).strip()
    except Exception:
        summary_md = ""

    # Minimal deterministic fallback to keep the pipeline unblocked
    if len(summary_md) < 60:
        lines = [f"# {topic}", "", "## Executive Summary", "- Overview unavailable; using fallback notes."]
        if sources:
            lines += ["", "## Landscape"] + [f"- [{s.get('title') or 'untitled'}]" for s in sources[:5]]
        lines += ["", "## Opportunities", "- Pilot a narrow use case with a single KPI"]
        lines += ["", "## Risks & Constraints", "- Data quality and governance; human oversight"]
        lines += ["", "## Quick Wins (<= 90 days)", "- 4-week pilot with weekly KPI readouts"]
        summary_md = "\n".join(lines)

    out = dict(bundle)
    out["summary"] = summary_md
    return out

