from __future__ import annotations
import os

class Settings:
    """
    Load all runtime config strictly from environment variables.
    Do NOT hard-code secrets or model names here to avoid Netlify secrets scanning.
    """

    # Groq
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")  # leave blank by default
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "")      # e.g., "llama-3.1-70b-versatile" in env only

    # Ollama (optional)
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "")  # e.g., http://127.0.0.1:11434
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "")        # e.g., "llama3.2:3b-instruct-q4_0"

    # App toggles
    GRAPHDECK_FAST: str = os.getenv("GRAPHDECK_FAST", "1")

settings = Settings()


