"""Multi-tenant registry. Adding a restaurant = drop a folder + run ingest."""
import json
from pathlib import Path
from .config import TENANTS_DIR

def list_tenants() -> list[dict]:
    """Return [{id, name, theme}] for every tenant folder that has config.json."""
    out = []
    for p in sorted(TENANTS_DIR.iterdir()):
        if not p.is_dir() or p.name.startswith("_"):
            continue
        cfg_path = p / "config.json"
        if not cfg_path.exists():
            continue
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        cfg["id"] = p.name
        out.append(cfg)
    return out


def get_tenant(tenant_id: str) -> dict | None:
    cfg_path = TENANTS_DIR / tenant_id / "config.json"
    if not cfg_path.exists():
        return None
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["id"] = tenant_id
    return cfg


def get_menu(tenant_id: str) -> dict | None:
    menu_path = TENANTS_DIR / tenant_id / "menu.json"
    if not menu_path.exists():
        return None
    return json.loads(menu_path.read_text(encoding="utf-8"))


def tenant_dir(tenant_id: str) -> Path:
    return TENANTS_DIR / tenant_id