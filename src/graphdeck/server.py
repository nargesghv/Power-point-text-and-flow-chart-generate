from __future__ import annotations

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=False)  # load .env before any env access

import os
import sys
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

# -------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------
HERE = Path(__file__).resolve().parent          # .../src/graphdeck
ROOT = HERE.parents[1]                          # repo root
SRC_DIR = ROOT / "src"
OUT = Path(os.getenv("GRAPHDECK_OUT_DIR", ROOT / "out"))
WEB = HERE / "web"

OUT.mkdir(parents=True, exist_ok=True)
WEB.mkdir(parents=True, exist_ok=True)

# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------
def slugify(s: str) -> str:
    import re
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "topic"

def expect_paths(topic: str, out_path: Optional[str] = None) -> dict:
    slug = slugify(topic)
    d = {
        "research_json": OUT / f"research_{slug}.json",
        "outline_json":  OUT / f"outline_{slug}.json",
        "slides_text":   OUT / f"slides_text_{slug}.txt",
        "diagram_slide3": OUT / f"diagram_{slug}_slide3.png",
        "deck_pptx":     Path(out_path) if out_path else OUT / f"{slug.replace('-', '_')}.pptx",
        "summary_md":    OUT / f"summary_{slug}.md",
        "blog_md":       OUT / f"blog_{slug}.md",
    }
    return {k: str(v) for k, v in d.items()}

def exists_map(paths: dict) -> dict:
    return {k: Path(v).exists() for k, v in paths.items()}

def run_cli(*args: str) -> tuple[str, str]:
    """
    Run 'python -m graphdeck.cli <args...>' from the repo root and return (stdout, stderr).
    Force UTF-8 and inject PYTHONPATH so the child can import 'graphdeck'.
    """
    cmd = [sys.executable, "-m", "graphdeck.cli", *args]
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    # Ensure the child can import the package (equivalent to running with --app-dir src)
    env["PYTHONPATH"] = str(SRC_DIR.resolve()) + os.pathsep + env.get("PYTHONPATH", "")

    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        shell=False,
    )
    if proc.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Command failed",
                "cmd": " ".join(cmd),
                "stdout": (proc.stdout or "")[-4000:],
                "stderr": (proc.stderr or "")[-4000:],
                "returncode": proc.returncode,
            },
        )
    return proc.stdout, proc.stderr

# -------------------------------------------------------------------
# Request models
# -------------------------------------------------------------------
class ResearchRequest(BaseModel):
    topic: str = Field(..., examples=["AI in marketing"])
    fast: bool = False

class SynthesizeRequest(BaseModel):
    topic: str
    research_json: Optional[str] = None
    fast: bool = False

class OutlineRequest(BaseModel):
    topic: str
    blog_md: Optional[str] = None
    research_json: Optional[str] = None
    fast: bool = False

class ContentRequest(BaseModel):
    topic: str
    outline_json: Optional[str] = None
    research_json: Optional[str] = None
    chart_slide_index: int = 3
    fast: bool = False

class RunAllRequest(BaseModel):
    topic: str
    chart_slide_index: int = 3
    fast: bool = False

# -------------------------------------------------------------------
# App
# -------------------------------------------------------------------
app = FastAPI(title="GraphDeck API", version="1.3.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten for prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated files and UI
app.mount("/out", StaticFiles(directory=str(OUT), html=False), name="out")
app.mount("/ui",  StaticFiles(directory=str(WEB), html=True),  name="web")

@app.get("/", include_in_schema=False)
def home_redirect():
    return RedirectResponse(url="/ui/")

# -------------------------------------------------------------------
# Health
# -------------------------------------------------------------------
@app.get("/health")
def health():
    return {
        "ok": True,
        "cwd": str(ROOT),
        "out_dir": str(OUT),
        "web_dir": str(WEB),
        "src_dir": str(SRC_DIR),
        "backends": {
            "groq": bool(os.getenv("GROQ_API_KEY")),
            "ollama": bool(shutil.which("ollama")),
        },
        "env": {
            "GROQ_MODEL": os.getenv("GROQ_MODEL"),
            "OLLAMA_BASE_URL": os.getenv("OLLAMA_BASE_URL"),
            "OLLAMA_MODEL": os.getenv("OLLAMA_MODEL"),
            "GRAPHDECK_FAST": os.getenv("GRAPHDECK_FAST"),
            "GRAPHDECK_NO_LLM": os.getenv("GRAPHDECK_NO_LLM"),
            "GRAPHDECK_DEBUG": os.getenv("GRAPHDECK_DEBUG"),
        },
    }

# -------------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------------
@app.post("/v1/research")
def api_research(req: ResearchRequest):
    paths = expect_paths(req.topic)
    args = ["research", req.topic, "--out-dir", str(OUT)]
    if req.fast:
        args += ["--fast"]
    stdout, stderr = run_cli(*args)
    slug = slugify(req.topic)
    artifacts = {
        "research_json": f"/out/research_{slug}.json"
    }
    return {"ok": True, "paths": paths, "exists": exists_map(paths),
            "artifacts": artifacts, "logs": {"stdout": stdout, "stderr": stderr}}

@app.post("/v1/synthesize")
def api_synthesize(req: SynthesizeRequest):
    slug = slugify(req.topic)
    research_json = req.research_json or str(OUT / f"research_{slug}.json")
    assert Path(research_json).exists(), f"Research JSON not found: {research_json}"
    args = ["synthesize", research_json, "--out-dir", str(OUT)]
    if req.fast:
        args += ["--fast"]
    stdout, stderr = run_cli(*args)
    paths = expect_paths(req.topic)
    artifacts = {
        "research_json": f"/out/research_{slug}.json",
        "summary_md":    f"/out/summary_{slug}.md",
    }
    return {"ok": True, "paths": paths, "exists": exists_map(paths),
            "artifacts": artifacts, "logs": {"stdout": stdout, "stderr": stderr}}

@app.post("/v1/outline")
def api_outline(req: OutlineRequest):
    paths = expect_paths(req.topic)
    args = ["outline", req.topic, "--out-dir", str(OUT)]
    if req.blog_md:
        args += ["--blog-md", req.blog_md]
    if req.research_json:
        args += ["--research-json", req.research_json]
    else:
        args += ["--research-json", paths["research_json"]]
    if req.fast:
        args += ["--fast"]
    stdout, stderr = run_cli(*args)
    slug = slugify(req.topic)
    artifacts = {
        "outline_json": f"/out/outline_{slug}.json",
        "blog_md":      f"/out/blog_{slug}.md",
    }
    return {"ok": True, "paths": paths, "exists": exists_map(paths),
            "artifacts": artifacts, "logs": {"stdout": stdout, "stderr": stderr}}

@app.post("/v1/content")
def api_content(req: ContentRequest):
    paths = expect_paths(req.topic)
    args = ["content", req.topic, "--out-dir", str(OUT), "--chart-slide-index", str(req.chart_slide_index)]
    if req.outline_json:
        args += ["--outline-json", req.outline_json]
    else:
        args += ["--outline-json", paths["outline_json"]]
    if req.research_json:
        args += ["--research-json", req.research_json]
    else:
        args += ["--research-json", paths["research_json"]]
    if req.fast:
        args += ["--fast"]
    stdout, stderr = run_cli(*args)

    slug = slugify(req.topic)
    text_file = OUT / f"slides_text_{slug}.txt"
    flowchart_file = OUT / f"diagram_{slug}_slide{req.chart_slide_index}.png"
    deck_file = OUT / f"{slug.replace('-', '_')}.pptx"

    artifacts: Dict[str, str] = {}
    if text_file.exists():      artifacts["text"] = f"/out/{text_file.name}"
    if flowchart_file.exists(): artifacts["flowchart"] = f"/out/{flowchart_file.name}"
    if deck_file.exists():      artifacts["deck_pptx"] = f"/out/{deck_file.name}"

    return {"ok": True, "paths": paths, "exists": exists_map(paths),
            "artifacts": artifacts, "logs": {"stdout": stdout, "stderr": stderr}}

@app.post("/v1/run_all")
def api_run_all(req: RunAllRequest):
    slug = slugify(req.topic)

    # 1) research
    run_cli("research", req.topic, "--out-dir", str(OUT), *(["--fast"] if req.fast else []))

    # 2) synthesize (creates summary and embeds into research json)
    run_cli("synthesize", str(OUT / f"research_{slug}.json"), "--out-dir", str(OUT), *(["--fast"] if req.fast else []))

    # 3) outline (blog generated from summary-backed research)
    run_cli(
        "outline", req.topic, "--out-dir", str(OUT),
        "--research-json", str(OUT / f"research_{slug}.json"),
        *(["--fast"] if req.fast else [])
    )

    # 4) content (+ slide-3 flowchart)
    run_cli(
        "content", req.topic, "--out-dir", str(OUT),
        "--outline-json", str(OUT / f"outline_{slug}.json"),
        "--research-json", str(OUT / f"research_{slug}.json"),
        "--chart-slide-index", str(req.chart_slide_index),
        *(["--fast"] if req.fast else [])
    )

    text     = OUT / f"slides_text_{slug}.txt"
    chart    = OUT / f"diagram_{slug}_slide{req.chart_slide_index}.png"
    outline  = OUT / f"outline_{slug}.json"
    research = OUT / f"research_{slug}.json"
    summary  = OUT / f"summary_{slug}.md"
    blog     = OUT / f"blog_{slug}.md"
    deck     = OUT / f"{slug.replace('-', '_')}.pptx"

    return {
        "ok": True,
        "artifacts": {
            "text":          f"/out/{text.name}" if text.exists() else None,
            "flowchart":     f"/out/{chart.name}" if chart.exists() else None,
            "outline_json":  f"/out/{outline.name}" if outline.exists() else None,
            "research_json": f"/out/{research.name}" if research.exists() else None,
            "summary_md":    f"/out/{summary.name}" if summary.exists() else None,
            "blog_md":       f"/out/{blog.name}" if blog.exists() else None,
            "deck_pptx":     f"/out/{deck.name}" if deck.exists() else None,
        },
    }

