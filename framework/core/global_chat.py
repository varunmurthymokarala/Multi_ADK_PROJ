"""Global concierge chat - deterministic routing across every restaurant.

The concierge never touches carts or sessions; it only recommends a tenant
and hands the user off to that restaurant's scoped assistant.
"""
from __future__ import annotations
import re
from .menu import find_items, menu_items
from .tenants import get_tenant, list_tenants

DIETS = ("vegan", "vegetarian", "gluten-free", "spicy")
STOP = {
    "i", "me", "my", "we", "us", "you", "a", "an", "the", "and", "or", "to",
    "for", "of", "in", "on", "is", "are", "do", "does", "can", "could", "would",
    "should", "will", "please", "thanks", "thank", "hi", "hello", "hey",
    "want", "wants", "eat", "food", "something", "anything", "show", "find",
    "get", "give", "have", "what", "which", "today", "tonight", "dinner",
    "lunch", "meal", "menu", "restaurant", "restaurants", "place", "places",
    "kitchen", "recommend", "recommendation", "suggest", "suggestion",
    "surprise", "craving", "crave", "good", "best", "cheap", "budget",
    "under", "below", "less", "than", "option", "options", "choice", "choices",
    "pick", "picks", "really", "very", "random",
}
MAIN_CATEGORIES = {"curries", "rice", "mains", "tacos", "burritos", "pizza", "pasta", "rolls"}


def _terms(message: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", message.lower())
            if len(t) > 1 and t not in STOP and not t.isdigit()]


def _cfg(tenant_id: str) -> dict:
    return get_tenant(tenant_id) or {}


def _line(item: dict, tenant_name: str) -> str:
    return f"- {item['name']} — ${item['price']:.2f} @ {tenant_name}"


def _overview(restaurants: list[dict]) -> str:
    lines = ["Here's who's cooking tonight:"]
    for r in restaurants:
        items = menu_items(r["id"])
        picks = ", ".join(f"{i['name']} ${i['price']:.2f}" for i in items[:2])
        lines.append(f"- {r['name']} ({r.get('tagline', '')}) — pickup ~{r.get('eta_minutes', 30)} min. Try: {picks}")
    lines.append("Tell me a dish, a cuisine, or a preference like 'vegan under $15' and I'll take you there.")
    return "\n".join(lines)


def global_reply(message: str) -> dict:
    text = message.strip().lower()
    words = text.split()
    terms = _terms(text)
    restaurants = list_tenants()
    digest = [{"id": r["id"], "name": r["name"], "tagline": r.get("tagline", ""),
               "eta_minutes": r.get("eta_minutes", 30)} for r in restaurants]
    base = {"restaurant_id": None, "restaurant_name": None, "restaurants": digest}

    # 1. Greeting / overview ------------------------------------------------
    wants_overview = (
        not terms
        or (len(words) <= 2 and set(words) & {"hi", "hello", "hey", "yo"})
        or set(terms) & {"restaurants", "options", "choices", "menus"}
    )
    if wants_overview:
        return {**base, "text": "Hi there! 👋\n" + _overview(restaurants)}

    # 2. Hours --------------------------------------------------------------
    if "hours" in text or set(terms) & {"open", "closing"}:
        lines = ["Here's when each kitchen is open:"]
        for r in restaurants:
            lines.append(f"- {r['name']}: {_cfg(r['id']).get('hours_text', '')}")
        return {**base, "text": "\n".join(lines)}

    # 3. Surprise me --------------------------------------------------------
    if set(terms) & {"surprise", "random"}:
        mains = [(r, i) for r in restaurants for i in menu_items(r["id"])
                 if i.get("category") in MAIN_CATEGORIES]
        if mains:
            r, i = mains[len(mains) // 2]
            text_lines = [
                f"Feeling bold? Try {i['name']} — ${i['price']:.2f} at {r['name']}.",
                f"Pickup ~{r.get('eta_minutes', 30)} min. Tap 'Go to' when you're ready.",
            ]
            return {**base, "text": "\n".join(text_lines),
                    "restaurant_id": r["id"], "restaurant_name": r["name"]}

    # Budget / diet parsing
    budget = None
    m = re.search(r"(?:under|below|less than|max|up to|within)\s*\$?\s*(\d+(?:\.\d+)?)", text)
    if m:
        budget = float(m.group(1))
    diet = next((d for d in DIETS if d in terms), None)
    if diet is None and "gluten" in terms and "free" in terms:
        diet = "gluten-free"
    core_terms = [t for t in terms if t not in DIETS and t != "free"]

    # 4. Budget (optionally with diet) --------------------------------------
    if budget is not None:
        matches = []
        for r in restaurants:
            for i in menu_items(r["id"]):
                if diet and diet not in (i.get("tags") or []):
                    continue
                if i["price"] > budget:
                    continue
                matches.append((r, i))
        matches.sort(key=lambda h: h[1]["price"])
        if matches:
            lines = [f"Here's what fits{' ' + diet if diet else ''} under ${budget:g}:"]
            lines += [_line(i, r["name"]) for r, i in matches[:6]]
            tids = {r["id"] for r, _ in matches}
            if len(tids) == 1:
                r = matches[0][0]
                lines.append(f"Everything here is at {r['name']} — tap 'Go to' when you're ready.")
                return {**base, "text": "\n".join(lines),
                        "restaurant_id": r["id"], "restaurant_name": r["name"]}
            lines.append("Say a dish or restaurant name to jump straight there.")
            return {**base, "text": "\n".join(lines)}

    # 5. Diet-only preference (no strong dish keywords) ---------------------
    if diet and len(core_terms) < 2:
        matches = [(r, i) for r in restaurants for i in menu_items(r["id"])
                   if diet in (i.get("tags") or [])]
        matches.sort(key=lambda h: h[1]["price"])
        if matches:
            lines = [f"Here are some {diet} picks across our kitchens:"]
            lines += [_line(i, r["name"]) for r, i in matches[:6]]
            tids = {r["id"] for r, _ in matches}
            if len(tids) == 1:
                r = matches[0][0]
                lines.append(f"All of these are at {r['name']} — tap 'Go to' when you're ready.")
                return {**base, "text": "\n".join(lines),
                        "restaurant_id": r["id"], "restaurant_name": r["name"]}
            lines.append("Say a dish or restaurant name to jump straight there.")
            return {**base, "text": "\n".join(lines)}

    # 6. Dish search across every menu --------------------------------------
    if budget is None:
        dish_hits = []
        for r in restaurants:
            for i in find_items(r["id"], message, limit=3):
                dish_hits.append((r, i))
        if dish_hits:
            counts: dict[str, int] = {}
            for r, i in dish_hits:
                counts[r["id"]] = counts.get(r["id"], 0) + 1
            top_id = max(counts, key=lambda k: counts[k])
            top = next(r for r in restaurants if r["id"] == top_id)
            ordered = ([h for h in dish_hits if h[0]["id"] == top_id]
                       + [h for h in dish_hits if h[0]["id"] != top_id])
            lines = ["Here's what I found:"]
            lines += [_line(i, r["name"]) for r, i in ordered[:6]]
            if counts[top_id] == len(dish_hits):
                lines.append(f"All of these are on the menu at {top['name']} — tap 'Go to' when you're ready.")
            else:
                lines.append(f"Best match: {top['name']}. Tap 'Go to' to jump over.")
            return {**base, "text": "\n".join(lines),
                    "restaurant_id": top_id, "restaurant_name": top["name"]}

    # 7. Cuisine keyword matching against tenant + menu corpus --------------
    keywords = core_terms or terms
    if keywords:
        scored = []
        for r in restaurants:
            c = _cfg(r["id"])
            corpus = " ".join([c.get("name", ""), c.get("tagline", ""), c.get("blurb", "")]).lower()
            corpus += " " + " ".join(f"{i['name']} {i['category']}" for i in menu_items(r["id"])).lower()
            score = sum(corpus.count(k) for k in keywords)
            scored.append((score, r))
        scored.sort(key=lambda s: (-s[0], s[1]["id"]))
        if scored and scored[0][0] > 0:
            r = scored[0][1]
            items = menu_items(r["id"])
            picks = [i for i in items
                     if any(k in (i["name"] + " " + i["category"]).lower() for k in keywords)] or items
            lines = [f"You want {r['name']} — {r.get('tagline', '')}.", "On the menu:"]
            lines += [_line(i, r["name"]) for i in picks[:4]]
            lines.append(f"Pickup ~{r.get('eta_minutes', 30)} min. Tap 'Go to' to start ordering.")
            return {**base, "text": "\n".join(lines),
                    "restaurant_id": r["id"], "restaurant_name": r["name"]}

    # 8. Fallback -----------------------------------------------------------
    return {**base, "text": (
        "I couldn't match that yet. Try a dish ('butter chicken'), a cuisine "
        "('sushi', 'tacos'), or a preference ('vegan under $15').\n" + _overview(restaurants)
    )}
