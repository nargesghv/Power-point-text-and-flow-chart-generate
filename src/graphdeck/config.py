from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # LLMs - Groq and Ollama only
    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.1-70b-versatile"

    OLLAMA_BASE_URL: str | None = None
    OLLAMA_MODEL: str = "llama3.2:3b-instruct-q4_0"

    # Search / assets (optional)
    SERPAPI_KEY: str | None = None
    PEXELS_API_KEY: str | None = None

    MCP_CONFIG_FILE: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()

