"""Central config — all from env or defaults. $0 project by default."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
TENANTS_DIR = ROOT / "tenants"
DATA_DIR.mkdir(exist_ok=True)
TENANTS_DIR.mkdir(exist_ok=True)

# Ollama (already running locally)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5-coder:7b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# Stripe (test mode = free). Leave empty to disable payments.
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# JWT signing key (random per install — change for prod)
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me-please-use-32-chars")
JWT_ALG = "HS256"

# SQLite DB (zero-cost, single file)
DB_PATH = DATA_DIR / "framework.db"

# ChromaDB persistence (local, free)
CHROMA_DIR = DATA_DIR / "chroma"

# Server
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))