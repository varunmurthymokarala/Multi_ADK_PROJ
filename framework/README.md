# Phase 1 local demo

This is the first local vertical slice of the architecture plan. Menu JSON is
the price source of truth. Cart and order mutations are deterministic; Ollama
handles only open-ended, menu-grounded questions.

## Run it

From this directory:

```powershell
python -m pip install -r requirements.txt
ollama pull qwen2.5-coder:7b
python -m uvicorn api.main:app --reload
```

Open `http://127.0.0.1:8000` and try:

- `show menu`
- `vegetarian options`
- `add 2 Chicken Biryani`
- `show cart`
- `What would you recommend for a vegetarian?`

The restaurant dropdown in the nav lists three sample tenants: `saffron-spice`
(full 41-item menu), plus demo tenants `sakura-sushi` and `taco-cantina` with
10-item menus each. Adding another restaurant is still just a new folder under
`tenants/` with `config.json` + `menu.json`.

## Verify it

```powershell
python -m unittest discover -s tests -v
```

The tests cover menu retrieval, dietary search, cart creation, server-side
pricing, a persisted `pending_payment` order, and the grounded Ollama prompt.

Stripe payment links, ADK routing, Chroma ingestion, WebSockets, and Redis are
the next milestones from the architecture plan.
