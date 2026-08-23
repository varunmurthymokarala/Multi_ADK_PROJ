"""In-memory session store for Phase 1; replace with Redis in Phase 2."""
from dataclasses import dataclass, field
from threading import Lock

@dataclass
class Session:
    tenant_id: str
    cart: list[dict] = field(default_factory=list)
    @property
    def total(self) -> float: return round(sum(line["price"] * line["quantity"] for line in self.cart), 2)

_sessions: dict[str, Session] = {}
_lock = Lock()
def get_session(session_id: str, tenant_id: str) -> Session:
    with _lock:
        session = _sessions.get(session_id)
        if not session or session.tenant_id != tenant_id:
            session = Session(tenant_id); _sessions[session_id] = session
        return session
def add_to_cart(session: Session, item: dict, quantity: int) -> Session:
    for line in session.cart:
        if line["item_id"] == item["id"]: line["quantity"] += quantity; return session
    session.cart.append({"item_id": item["id"], "name": item["name"], "price": item["price"], "quantity": quantity})
    return session
