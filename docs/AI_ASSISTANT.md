# AI Market Assistant (DeepSeek / OpenAI-compatible)

A natural-language analyst layered on top of the bundled Bayut + PropertyFinder
data. Ask it to summarize listings, find rising areas, detect underpriced
properties, compare communities, explain price moves, recommend investments,
predict yield trends, generate reports, or answer free-form questions like:

- "Where can I buy a 2-bedroom apartment below AED 1.5M with the highest appreciation potential?"
- "Which Dubai areas grew the fastest in the last 24 months?"
- "Show projects from developers with strong resale performance."

Open **`ui/ai-assistant.html`** in your browser. It is self-contained (no
backend/Docker needed) and is wired for **DeepSeek** by default.

> On the "DeepSeek V4" model name: DeepSeek's official API exposes `deepseek-chat`
> (latest V3.x family) and `deepseek-reasoner` (R1). There is no official "V4"
> at time of writing — the model is fully configurable, so the moment DeepSeek
> releases a V4 you just set `AI_MODEL=deepseek-v4` (or whatever they name it)
> and it's used automatically. Everything else is model-agnostic.

## How it stays honest (grounding, not hallucination)

The assistant does **not** let the model invent numbers. Before every question,
a compact, pre-computed market context is injected as the system prompt, built
by `tools/build_market_insights.py`:

- dataset snapshot (listings/rents/sales counts, areas, history span)
- fastest-appreciating & declining areas (CAGR + sample size + period)
- highest gross rental yields (median rent ÷ median sale)
- potentially underpriced rentals (≥30% below area median)
- full per-area stats (median rent, sale, yield, history)

The system prompt instructs the model to quote figures *with their sample size
and period* and to say "the data doesn't cover that" rather than fabricate.
Verified live: a "rising areas" query returned an exact ranked table (Mudon
19.8%/yr n=5, Aljada 11%/yr n=20, …) and explicitly refused to invent causes.

## Files added

```
tools/ai_proxy.py                  # stdlib local proxy → DeepSeek (key stays server-side)
                                   #   GET /ai/health · GET /ai/settings · POST /ai/settings · POST /ai/ask · POST /ai/test
tools/build_market_insights.py     # builds the AI context bundle
ui/data/market-insights.js         # GENERATED — window.MARKET_INSIGHTS
ui/ai-assistant.html               # the chat UI (quick actions + free text + context panel)
ui/settings.html                   # settings UI — enter/test/save your DeepSeek key (no file editing)
.ai.env.example                    # config template (copy to .ai.env, gitignored)
.vscode/tasks.json                 # + "Start AI Proxy (DeepSeek assistant)" task
ui/index.html, ui/pricing-history.html   # + links to the assistant
```

## Setup — pick one model source

**Easiest: open `ui/settings.html`** and enter your DeepSeek key in the form
(click the 🟣 DeepSeek preset, paste the key, **Test connection**, **Save**).
The page persists settings to `.ai.env` and applies them live — no restart,
no editing files by hand. Then start the proxy task.

### Option A — DeepSeek directly (recommended, what you asked for)
1. Get an API key at <https://platform.deepseek.com>.
2. Either set it via **`ui/settings.html`**, or in `dubai-estate/`:
   ```bash
   cp .ai.env.example .ai.env
   # edit .ai.env:
   #   AI_API_KEY=sk-your-deepseek-key
   #   AI_BASE_URL=https://api.deepseek.com
   #   AI_MODEL=deepseek-chat          # or deepseek-reasoner / deepseek-v4 when available
   ```
3. Run the **"Start AI Proxy (DeepSeek assistant)"** task (Terminal → Run Task),
   or `python3 tools/ai_proxy.py` from `dubai-estate/`.

### Option B — reuse the running cli-proxy-api (no key needed today)
If you already run the Antigravity/cli-proxy-api on `127.0.0.1:8317`, point at it
(check `curl http://127.0.0.1:8317/v1/models` for model ids):
```bash
AI_API_KEY=sk-local-proxy-key-2024 \
AI_BASE_URL=http://127.0.0.1:8317 \
AI_MODEL=gpt-5.6-terra \
python3 tools/ai_proxy.py
```
(DeepSeek isn't currently configured in that proxy — only Option A gives you a
DeepSeek model. Option B works instantly with whatever models the proxy exposes.)

## Using it

- **Quick actions**: Summarize market · Rising areas · Underpriced deals ·
  Yield trends · Investment ideas · Full report.
- **Examples**: the three questions above + a community comparison.
- **Free text**: type anything; Enter to send, Shift+Enter for a newline.
- The **right-hand panel** shows exactly what data is being injected.

The status pill goes green ("AI online · \<model\>") when the proxy is up and a
key is configured; red when it isn't (with instructions in the chat).

## Why a proxy (instead of calling DeepSeek from the page)

- Keeps the API key off the client (page is opened via `file://`).
- Avoids CORS — DeepSeek/OpenAI block cross-origin browser calls.
- Makes the endpoint swappable (DeepSeek, the cli-proxy-api, Ollama, …) by
  changing one config value, with zero UI changes.

## Refreshing the data

After updating `data/bayut/`:
```bash
python3 tools/build_bayut_history.py     # history page bundle
python3 tools/build_market_insights.py   # AI context bundle
```

## Architecture / extending

- **Proxy** (`tools/ai_proxy.py`): stdlib only, exposes `GET /ai/health` and
  `POST /ai/ask {messages, model?, temperature?}` → `{content, model, usage, ms}`.
- **Backend upgrade**: to fold this into the governed FastAPI stack (when
  Postgres is up), the same `buildContext()` logic can move to an
  `api/src/dxb_api/routers/ai.py` endpoint that queries the marts instead of the
  JS bundle, and the page's `PROXY` constant points there. The proxy can be
  dropped at that point.
- **Model tuning**: edit the `SYS` prompt in `ui/ai-assistant.html` to change
  tone, strictness, or output format.
