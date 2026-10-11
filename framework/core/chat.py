"""Safe chat routing with deterministic ordering, checkout, and an Ollama fallback."""
import re

from .llm import chat as ollama_chat
from .menu import find_items, format_items, get_item, menu_items
from .orders import create_order
from .sessions import add_to_cart, get_session
from .tenants import get_tenant


# --- Order intent parsing ---------------------------------------------------

ORDER_PHRASES = (
    "i'd like", "i would like", "i'd love", "let me have", "let me get",
    "give me", "bring me", "i'll have", "i will have", "can i have",
    "can i get", "may i have", "may i get", "i want", "i need",
    "please add", "i'd like to have", "i want to have",
)
ORDER_VERBS = (
    "add", "order", "want", "like", "have", "get", "give", "need",
    "place", "put", "take", "try", "grab",
)
ORDER_FILLER = ("please", "thanks", "thank you", "now")
ITEM_STOP = {
    "a", "an", "some", "any", "the", "of", "for", "to", "with", "on", "in",
    "me", "my", "i", "you", "us", "we", "and", "or",
    "do", "does", "did", "is", "are", "was", "were", "be", "been", "being",
    "can", "could", "would", "should", "will", "may", "might", "shall",
    "has", "had", "having",
    "what", "which", "where", "when", "who", "whom", "whose", "why", "how",
    "there", "here", "this", "that", "these", "those",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
}
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "a": 1, "an": 1,
}

CHECKOUT_PHRASES = (
    "checkout", "place my order", "place the order", "place order",
    "confirm my order", "confirm order", "i'm done", "im done",
    "that's all", "thats all", "i'm ready", "im ready",
    "submit order", "complete order", "finalize", "pay now",
)


def _resolve_item(tenant_id: str, name: str) -> dict | None:
    """Exact name/id match, then best fuzzy match from the menu."""
    exact = get_item(tenant_id, name)
    if exact:
        return exact
    candidates = find_items(tenant_id, name, limit=1)
    return candidates[0] if candidates else None


def _parse_order_intent(message: str) -> tuple[int, str, bool] | None:
    """Return (quantity, item_text, has_verb) if the message looks like an order, else None."""
    text = message.lower().strip().rstrip("?!.")
    if not text:
        return None

    # Find a quantity (digit or word). Reject ambiguity.
    digit_match = re.search(r"\b(\d+)\b", text)
    word_qty = None
    for word, num in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", text):
            if word_qty:
                return None
            word_qty = (word, num)
    if digit_match and word_qty:
        return None

    if digit_match:
        quantity = int(digit_match.group(1))
        text_no_qty = text.replace(digit_match.group(0), " ", 1)
    elif word_qty:
        quantity = word_qty[1]
        text_no_qty = re.sub(rf"\b{word_qty[0]}\b", " ", text, count=1)
    else:
        quantity = None
        text_no_qty = text

    has_verb = any(phrase in text_no_qty for phrase in ORDER_PHRASES) or any(
        re.search(rf"\b{verb}\b", text_no_qty) for verb in ORDER_VERBS
    )

    if quantity is None and not has_verb:
        return None
    if quantity is None:
        quantity = 1
    if not (0 < quantity <= 20):
        return None

    work = text_no_qty
    for phrase in ORDER_PHRASES:
        work = work.replace(phrase, " ")
    for verb in ORDER_VERBS:
        work = re.sub(rf"\b{verb}\b", " ", work)
    for filler in ORDER_FILLER:
        work = re.sub(rf"\b{filler}\b", " ", work)
    work = re.sub(r"\b(?:orders?|pieces?|plates?|servings?|portions?)\s+of\b", " ", work)
    work = re.sub(r"\b(?:orders?|pieces?|plates?|servings?|portions?)\b", " ", work)
    work = re.sub(r"\bof\b", " ", work)
    tokens = [t for t in re.findall(r"[a-z0-9]+", work) if t and t not in ITEM_STOP]
    item_name = " ".join(tokens).strip()
    if not item_name:
        return None

    return (quantity, item_name, has_verb)


def _cart_summary(cart: list[dict], total: float) -> str:
    lines = [
        f"- {line['quantity']} x {line['name']} — ${line['price'] * line['quantity']:.2f}"
        for line in cart
    ]
    return "\n".join(lines) + f"\n**Cart total: ${total:.2f}**"


def _eta(tenant: dict) -> int:
    return int(tenant.get("eta_minutes", 30))


# --- Menu context for the LLM -----------------------------------------------

def _menu_context(tenant_id: str) -> str:
    """Give the model only menu facts it is allowed to use."""
    return "\n".join(
        f"- {item['name']} | ${item['price']:.2f} | {item['category']} | "
        f"{item.get('description', 'No description')} | "
        f"allergens: {', '.join(item.get('allergens', [])) or 'none listed'} | "
        f"tags: {', '.join(item.get('tags', [])) or 'none listed'}"
        for item in menu_items(tenant_id)
    )


def _unavailable_requested_item(message: str) -> str | None:
    """Recognize a direct request for a dish that has no menu match."""
    match = re.search(
        r"\b(?:can i have|do you have|i want|i would like)\s+(?:one|a|an|\d+)?\s*(?P<item>[a-z][a-z -]{1,60})[?!.]*$",
        message.lower().strip(),
    )
    if not match:
        return None
    item = match.group("item").strip().removesuffix(" please").strip()
    return None if item in {"menu", "the menu"} else item.title()


# --- Deterministic routing ---------------------------------------------------

def _deterministic_reply(tenant_id: str, session_id: str, message: str) -> dict | None:
    tenant = get_tenant(tenant_id)
    if not tenant:
        raise ValueError("Unknown tenant")

    session = get_session(session_id, tenant_id)
    lower = message.strip().lower().rstrip("?!.")
    eta = _eta(tenant)

    # 1. Checkout intent --------------------------------------------------
    if any(phrase in lower for phrase in CHECKOUT_PHRASES):
        if not session.cart:
            response = (
                "Your cart is empty. Add a few dishes first, then say **'place my order'** when you're ready."
            )
            return {"text": response, "cart": list(session.cart), "total": session.total,
                    "source": "deterministic", "order_id": None, "eta_minutes": eta}
        order = create_order(tenant_id, session.cart, session.total)
        placed_cart = list(session.cart)
        placed_total = session.total
        session.cart = []
        response = (
            f"\U0001f389 **Thanks for placing your order!**\n"
            f"Order #{order['id'][:8]} is confirmed.\n"
            f"**Total: ${placed_total:.2f}**\n"
            f"Your order will be ready in about **{eta} minutes**. "
            f"We'll see you soon!"
        )
        return {"text": response, "cart": placed_cart, "total": placed_total,
                "source": "checkout", "order_id": order["id"], "eta_minutes": eta}

    # 2. Order intent (add to cart) ----------------------------------------
    intent = _parse_order_intent(message)
    if intent:
        quantity, item_name, has_verb = intent
        item = _resolve_item(tenant_id, item_name)
        if item and 0 < quantity <= 20:
            add_to_cart(session, item, quantity)
            line_total = item["price"] * quantity
            cart_text = _cart_summary(session.cart, session.total)
            hint = "\nSay **'place my order'** when you're done!" if has_verb else ""
            response = (
                f"\u2705 Added **{quantity} x {item['name']}** (${line_total:.2f}) to your cart.\n\n"
                f"{cart_text}\n\n"
                f"Ready in about **{eta} minutes** when you check out.{hint}"
            ).rstrip()
            return {"text": response, "cart": list(session.cart), "total": session.total,
                    "source": "deterministic", "order_id": None, "eta_minutes": eta}
        if not item:
            if item_name.lower() in {"menu", "the menu"}:
                return None
            unavailable = item_name.title()
            response = f"Sorry, {unavailable} is not available on our current menu."
            return {"text": response, "cart": list(session.cart), "total": session.total,
                    "source": "deterministic", "order_id": None, "eta_minutes": eta}
        response = "I couldn't add that. Use a quantity between 1 and 20, e.g. 'add 2 Chicken Biryani'."
        return {"text": response, "cart": list(session.cart), "total": session.total,
                "source": "deterministic", "order_id": None, "eta_minutes": eta}

    # 3. Cart view ---------------------------------------------------------
    if any(word in lower.split() for word in ("cart", "total")):
        if not session.cart:
            response = "Your cart is empty. Try 'add 2 Vegetable Samosa' to get started."
        else:
            response = "Here's your cart:\n" + _cart_summary(session.cart, session.total)
        return {"text": response, "cart": list(session.cart), "total": session.total,
                "source": "deterministic", "order_id": None, "eta_minutes": eta}

    # 4. Full menu ---------------------------------------------------------
    if "menu" in lower and len(lower.split()) <= 4:
        response = "Here are a few options:\n" + format_items(menu_items(tenant_id)[:5])
        return {"text": response, "cart": list(session.cart), "total": session.total,
                "source": "deterministic", "order_id": None, "eta_minutes": eta}

    # 5. Item search -------------------------------------------------------
    matches = find_items(tenant_id, message)
    if not matches:
        unavailable = _unavailable_requested_item(message)
        if not unavailable:
            return None
        response = f"Sorry, {unavailable} is not available on our current menu."
    else:
        response = format_items(matches)

    return {"text": response, "cart": list(session.cart), "total": session.total,
            "source": "deterministic", "order_id": None, "eta_minutes": eta}


async def reply(tenant_id: str, session_id: str, message: str) -> dict:
    """Use Ollama only for open-ended questions; cart mutations remain deterministic."""
    deterministic = _deterministic_reply(tenant_id, session_id, message)
    if deterministic:
        return deterministic

    tenant = get_tenant(tenant_id)
    session = get_session(session_id, tenant_id)
    eta = _eta(tenant)
    messages = [
        {
            "role": "system",
            "content": (
                f"You are the menu assistant for {tenant['name']}. "
                f"You are a helpful assistant for a restaurant. "
                f"You answer ONLY from the menu facts below. "
                f"Do not invent dishes, ingredients, allergens, prices, hours, policies, or availability. "
                f"If the facts do not answer the question, say so plainly. "
                f"Do not claim to change a cart or create an order. "
                f"For an order, tell the customer to use: add <quantity> <exact menu item name>.\n\n"
                f"MENU FACTS:\n{_menu_context(tenant_id)}"
            ),
        },
        {"role": "user", "content": message},
    ]
    try:
        response = await ollama_chat(messages)
    except Exception:
        return {"text": "I couldn't find a matching menu item. Try a dish name or category.",
                "cart": list(session.cart), "total": session.total,
                "source": "fallback", "order_id": None, "eta_minutes": eta}
    return {"text": response.strip(), "cart": list(session.cart), "total": session.total,
            "source": "ollama", "order_id": None, "eta_minutes": eta}
