"""Small SQLite order store for the local Phase 1 demo."""
import json, sqlite3, uuid
from datetime import UTC, datetime
from .config import DB_PATH

def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH); connection.row_factory = sqlite3.Row
    connection.execute("CREATE TABLE IF NOT EXISTS orders (id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, status TEXT NOT NULL, total REAL NOT NULL, items_json TEXT NOT NULL, created_at TEXT NOT NULL)")
    return connection
def create_order(tenant_id: str, items: list[dict], total: float) -> dict:
    order = {"id": uuid.uuid4().hex, "tenant_id": tenant_id, "status": "pending_payment", "total": total, "items": items, "created_at": datetime.now(UTC).isoformat()}
    with _connection() as c: c.execute("INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)", (order["id"], order["tenant_id"], order["status"], order["total"], json.dumps(items), order["created_at"]))
    return order
def get_order(tenant_id: str, order_id: str) -> dict | None:
    with _connection() as c: row = c.execute("SELECT * FROM orders WHERE id = ? AND tenant_id = ?", (order_id, tenant_id)).fetchone()
    if not row: return None
    order = dict(row); order["items"] = json.loads(order.pop("items_json")); return order
