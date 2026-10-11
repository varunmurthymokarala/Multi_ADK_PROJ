from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from core.auth import (
    auth_config, create_local_user, create_reset_code, make_token,
    public_user, reset_password, upsert_google_user, user_from_token,
    verify_google_id_token, verify_local_user,
)
from core.chat import reply
from core.global_chat import global_reply
from core.menu import get_item
from core.orders import create_order, get_order
from core.sessions import add_to_cart, get_session
from core.tenants import get_menu, get_tenant, list_tenants

app = FastAPI(title="Restaurant Chat Framework", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
WEB_DIR = Path(__file__).resolve().parent.parent / "web"
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    session_id: str | None = None
class CartItem(BaseModel):
    item_id: str
    quantity: int = Field(ge=1, le=20)
class OrderRequest(BaseModel):
    session_id: str | None = None
    items: list[CartItem] = []
class CheckoutRequest(BaseModel):
    session_id: str
class GlobalChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=6, max_length=100)
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=1, max_length=100)
class GoogleRequest(BaseModel):
    id_token: str = Field(min_length=10)
class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=120)
class ResetPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=120)
    code: str = Field(min_length=4, max_length=10)
    password: str = Field(min_length=6, max_length=100)
def _eta_minutes(tenant: dict) -> int:
    return int(tenant.get("eta_minutes", 30))
def require_tenant(tenant_id: str) -> dict:
    tenant = get_tenant(tenant_id)
    if not tenant: raise HTTPException(404, "Tenant not found")
    return tenant
@app.get("/health")
def health(): return {"status": "ok"}
@app.get("/api/auth/config")
def auth_cfg(): return auth_config()
@app.post("/api/auth/register")
def register(body: RegisterRequest):
    try:
        user = create_local_user(body.name, body.email, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"token": make_token(user), "user": public_user(user)}
@app.post("/api/auth/login")
def login(body: LoginRequest):
    try:
        user = verify_local_user(body.email, body.password)
    except ValueError as e:
        raise HTTPException(401, str(e))
    return {"token": make_token(user), "user": public_user(user)}
@app.post("/api/auth/google")
async def google_login(body: GoogleRequest):
    try:
        info = await verify_google_id_token(body.id_token)
        user = upsert_google_user(info)
    except ValueError as e:
        raise HTTPException(401, str(e))
    return {"token": make_token(user), "user": public_user(user)}
@app.post("/api/auth/forgot")
def forgot_password(body: ForgotPasswordRequest):
    try:
        dev_code = create_reset_code(body.email)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if dev_code:
        return {"sent": False, "dev_code": dev_code,
                "detail": "Email delivery is not configured on this server. Use this reset code (local dev mode)."}
    return {"sent": True, "detail": "Reset code sent to your Gmail inbox."}
@app.post("/api/auth/reset")
def reset_password_route(body: ResetPasswordRequest):
    try:
        reset_password(body.email, body.code, body.password)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "detail": "Password updated. Please log in."}
@app.get("/api/auth/me")
def me(request: Request):
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    user = user_from_token(token) if token else None
    if not user:
        raise HTTPException(401, "Not signed in")
    return public_user(user)
@app.get("/api/tenants")
def tenants(): return list_tenants()
@app.get("/api/menu/{tenant_id}")
def menu(tenant_id: str): require_tenant(tenant_id); return get_menu(tenant_id)
@app.post("/api/chat/global")
def chat_global(body: GlobalChatRequest):
    return global_reply(body.message)
@app.post("/api/chat/{tenant_id}")
async def chat(tenant_id: str, body: ChatRequest):
    require_tenant(tenant_id); session_id = body.session_id or uuid4().hex
    result = await reply(tenant_id, session_id, body.message)
    result.setdefault("order_id", None)
    result.setdefault("eta_minutes", _eta_minutes(require_tenant(tenant_id)))
    return {"session_id": session_id, **result}
@app.post("/api/orders/{tenant_id}")
def order(tenant_id: str, body: OrderRequest):
    require_tenant(tenant_id); session = get_session(body.session_id or uuid4().hex, tenant_id)
    for requested in body.items:
        item = get_item(tenant_id, requested.item_id)
        if not item: raise HTTPException(400, f"Unknown menu item: {requested.item_id}")
        add_to_cart(session, item, requested.quantity)
    if not session.cart: raise HTTPException(400, "Cart is empty")
    order_record = create_order(tenant_id, session.cart, session.total)
    order_record["eta_minutes"] = _eta_minutes(require_tenant(tenant_id))
    return order_record
@app.post("/api/checkout/{tenant_id}")
def checkout(tenant_id: str, body: CheckoutRequest):
    tenant = require_tenant(tenant_id)
    session = get_session(body.session_id, tenant_id)
    if session.tenant_id != tenant_id or not session.cart:
        raise HTTPException(400, "Cart is empty for this session")
    order_record = create_order(tenant_id, session.cart, session.total)
    order_record["eta_minutes"] = _eta_minutes(tenant)
    placed_cart = list(session.cart)
    placed_total = session.total
    session.cart = []
    return {
        "order": order_record,
        "cart": placed_cart,
        "total": placed_total,
        "eta_minutes": order_record["eta_minutes"],
    }
@app.get("/api/orders/{tenant_id}/{order_id}")
def order_status(tenant_id: str, order_id: str):
    require_tenant(tenant_id); order_record = get_order(tenant_id, order_id)
    if not order_record: raise HTTPException(404, "Order not found")
    order_record["eta_minutes"] = _eta_minutes(require_tenant(tenant_id))
    return order_record
@app.get("/")
def home(): return FileResponse(WEB_DIR / "login.html")
@app.get("/app")
def app_page(): return FileResponse(WEB_DIR / "index.html")
@app.get("/login")
def login_page(): return RedirectResponse("/", status_code=302)
