# 🍽️ Restaurant Real-Time Chat Support System

> A multi-tenant, LLM-driven chat framework for restaurants — order placement, queue handling, and customer support.

[![Stack](https://img.shields.io/badge/stack-ADK%20·%20Qwen2.5--Coder%20·%20FastAPI%20·%20ChromaDB%20·%20MCP-blueviolet)](#architecture)
[![LLM](https://img.shields.io/badge/LLM-local%20via%20Ollama-orange)](#architecture)
[![License](https://img.shields.io/badge/license-MIT-green)](#license)

---

## 📖 Overview

This repository contains the **architecture plan** for a production-grade, real-time chat support system built specifically for restaurants. The same framework can be deployed for many restaurants (multi-tenant) with no code changes — just drop a new menu and config.

### Why this exists

Restaurants lose revenue when:
- 🍕 Customers walk away because the queue looks huge
- 📞 Phone lines are jammed during peak hours
- 🕐 Staff spend time answering repetitive menu questions

This system handles all three via a chat interface accessible from:
- **Web widget** embedded in any restaurant website (one `<script>` tag)
- **QR code** on table tents / receipts → opens a mobile-friendly landing page
- **Mobile PWA** installable on customer phones
- **Voice** (Phase 6, optional)

---

## 🚀 Use Cases

| For the customer | For the operator |
|---|---|
| "What's on the menu?" | Onboard a new restaurant in < 30 min |
| "Any vegan options?" | Upload menu → auto-vectorized |
| "I want 2 margheritas for pickup" | See live orders + chat history |
| "How long is the queue?" | Receive Stripe payments directly |
| "Can I pay now, pick up later?" | Multi-tenant from day one |

---

## 🏗️ Architecture

See **[`restaurant-chat-architecture.html`](./restaurant-chat-architecture.html)** for the complete plan with diagrams, code samples, and a 6-phase build roadmap.

### High-Level Flow

```
┌────────────────┐    ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
│ Customer       │───▶│ FastAPI        │───▶│ ADK            │───▶│ Sub-Agents     │
│ (Web / QR /    │ WS │ + Auth         │    │ Orchestrator   │    │ Menu · Order · │
│  PWA / Voice)  │    │ + Rate Limit   │    │ (Qwen2.5-Coder)│    │ Payment · Queue│
└────────────────┘    └────────────────┘    └────────────────┘    └───────┬────────┘
                                                                           │
                                          ┌────────────────────────────────┼────────────────────────────────┐
                                          ▼                                ▼                                ▼
                                  ┌──────────────┐                ┌──────────────┐                ┌──────────────┐
                                  │ ChromaDB     │                │ Postgres +   │                │ MCP Servers  │
                                  │ (per-tenant  │                │ Redis        │                │ stripe · pos │
                                  │  vector DB)  │                │ (state)      │                │ · sms · etc. │
                                  └──────────────┘                └──────────────┘                └──────────────┘
```

---

## 🧰 Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Agent Framework | **Google ADK** | Composable agents, native tool calling |
| LLM | **Qwen2.5-Coder:7b** (Ollama) | Strong reasoning, runs locally, no API costs |
| Embeddings | `nomic-embed-text` or `bge-small` | Lightweight via Ollama |
| Vector DB | **ChromaDB** | Per-tenant collections, OSS |
| API | **FastAPI** + Uvicorn | Async-native, WebSocket |
| MCP | Model Context Protocol | Standard tool-server interface |
| Database | Postgres 16 + SQLAlchemy | Tenants, orders, audit log |
| Cache / Sessions | Redis 7 | Live queue, TTL sessions |
| Web Widget | Vanilla JS + Shadow DOM | One `<script>` tag, zero impact on host site |
| Mobile | PWA (service worker) | Installable, push notifications |
| Payments | Stripe (test mode first) | Payment Links via MCP |
| Deployment | Docker Compose → K8s | Local parity with prod |

---

## 📂 Repository Layout

```
Multi_ADK_PROJ/
├── README.md                          # This file
└── restaurant-chat-architecture.html  # Full architecture document (open in browser)
```

The architecture document is a **single self-contained HTML file** — no external dependencies, print-friendly, mobile-responsive. Open it in any browser.

---

## 🛣️ Build Roadmap

Six phases, each independently shippable:

1. **Foundation** — FastAPI + Ollama + ADK + one tenant, web widget, RAG over sample menu, end-to-end Stripe test link.
2. **Multi-tenant core** — Tenant folder structure, ingestion pipeline, auth, admin dashboard.
3. **All channels** — QR landing, PWA, push notifications for "order ready".
4. **Queue & POS** — Real-time queue lookup, optional kitchen-printer integration via `pos-mcp`.
5. **Hardening** — Rate limits, observability, security audit, load testing.
6. **Voice (optional)** — Whisper STT + browser TTS for hands-free ordering.

Full acceptance criteria per phase are in the architecture document, §14.

---

## ✅ Pre-Build Checklist

Before writing code, confirm:

- [ ] Target language(s) for menus and chat (English first)
- [ ] Stripe test account + webhook secret
- [ ] Postgres hosting plan (local Docker → Neon/Supabase in prod)
- [ ] Domain + TLS cert (e.g. `chat.yourcompany.com`)
- [ ] Menu JSON schema agreed with a pilot restaurant
- [ ] Observability stack (start simple: JSON logs → Loki)
- [ ] Notification provider (web-push first, Twilio SMS later)
- [ ] Orchestrator system prompt drafted for pilot restaurant's voice

---

## 🚧 Status

> **Current phase:** 📝 Architecture complete — not yet building code.
>
> Next milestone: **Phase 1** — scaffold `restaurant-chat-framework/` repo with FastAPI + ADK + one tenant + Stripe test mode.

---

## 📜 License

MIT — see [LICENSE](./LICENSE) (add when code lands).

---

## 🙌 Acknowledgements

- [Google ADK](https://github.com/google/adk-python) — agent orchestration
- [Ollama](https://ollama.com) — local LLM runtime
- [Qwen2.5-Coder](https://huggingface.co/Qwen) — reasoning model
- [ChromaDB](https://www.trychroma.com) — vector database
- [Model Context Protocol](https://modelcontextprotocol.io) — tool server standard
- [FastAPI](https://fastapi.tiangolo.com) — async web framework
- [Stripe](https://stripe.com) — payments
