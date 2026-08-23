"""Async Ollama client for chat + embeddings. Pure local, $0."""
import httpx
from .config import OLLAMA_URL, LLM_MODEL, EMBED_MODEL

async def chat(messages: list[dict], temperature: float = 0.3,
               model: str | None = None) -> str:
    """Call Ollama /api/chat with a list of {role, content} messages."""
    payload = {
        "model": model or LLM_MODEL,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{OLLAMA_URL}/api/chat", json=payload)
        r.raise_for_status()
        return r.json()["message"]["content"]


async def embed(text: str) -> list[float]:
    """Embed a single string via Ollama."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(f"{OLLAMA_URL}/api/embeddings",
                         json={"model": EMBED_MODEL, "prompt": text})
        r.raise_for_status()
        return r.json()["embedding"]