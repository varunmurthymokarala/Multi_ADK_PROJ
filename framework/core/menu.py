"""Safe menu lookup helpers. Menu JSON remains the source of truth for prices."""
from __future__ import annotations
import re
from .tenants import get_menu

STOP_WORDS = {"a", "an", "and", "are", "can", "do", "for", "have", "i", "is", "it", "me", "one", "please", "the", "to", "what", "with", "would", "you"}

def menu_items(tenant_id: str) -> list[dict]:
    menu = get_menu(tenant_id)
    return [item for item in (menu or {}).get("items", []) if item.get("available", True)]

def find_items(tenant_id: str, query: str, limit: int = 5) -> list[dict]:
    terms = {
        term for term in re.findall(r"[a-z0-9]+", query.lower())
        if len(term) > 1 and term not in STOP_WORDS
    }
    ranked = []
    for item in menu_items(tenant_id):
        haystack = " ".join([item.get("name", ""), item.get("description", ""), item.get("category", ""), " ".join(item.get("allergens", [])), " ".join(item.get("tags", []))]).lower()
        menu_words = set(re.findall(r"[a-z0-9]+", haystack))
        score = len(terms & menu_words)
        if score: ranked.append((score, item))
    ranked.sort(key=lambda result: (-result[0], result[1]["name"]))
    return [item for _, item in ranked[:limit]]

def get_item(tenant_id: str, item_id_or_name: str) -> dict | None:
    needle = item_id_or_name.strip().lower()
    return next((item for item in menu_items(tenant_id) if item.get("id", "").lower() == needle or item.get("name", "").lower() == needle), None)

def format_items(items: list[dict]) -> str:
    if not items: return "I couldn't find a matching menu item. Try a dish name or category."
    return "\n".join(f"- {item['name']} — ${item['price']:.2f} ({item['category']})" + (f": {item['description']}" if item.get("description") else "") for item in items)
