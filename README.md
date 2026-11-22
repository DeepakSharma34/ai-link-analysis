# AI Link Analysis (FastAPI + LLM)

`POST /link-analysis` takes a website URL, fetches and cleans the page content, sends it to an LLM, and returns five validated JSON sections: competitors, top-5 search queries, SEO improvements, top-5 services, and target audience.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate      # Windows CMD: .venv\Scripts\activate   |  PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env           # Windows: copy .env.example .env
# add GEMINI_API_KEY to .env (free key: https://aistudio.google.com/apikey)
uvicorn app.main:app --host 0.0.0.0 --port 4000
```
Docs: http://localhost:4000/docs  ·  Tests: `pytest -q`  ·  Docker: `docker build -t link-analysis . && docker run -p 4000:4000 --env-file .env link-analysis`

```bash
curl -X POST http://localhost:4000/link-analysis -H "Content-Type: application/json" \
     -d '{"url": "https://basecamp.com"}'
# Windows CMD: curl -X POST http://localhost:4000/link-analysis -H "Content-Type: application/json" -d "{\"url\": \"https://basecamp.com\"}"
```

## How it works

1. **Validate URL** (`utils/validators.py`): http/https only, no credentials, ports 80/443 only.
2. **SSRF protection**: the host is DNS-resolved and rejected unless every IP is globally routable (blocks loopback, RFC1918, link-local/cloud metadata `169.254.169.254`, IPv6 and IPv4-mapped IPv6). Redirects are followed manually and **each hop is re-validated**. Page size is capped at 2 MB. *Known limit:* a DNS-rebinding race between check and connect is not fully closed; for production, pin the validated IP in the HTTP transport or run behind an egress proxy.
3. **Extract** (`website_extractor.py`): title, meta/OG tags, JSON-LD, headings, deduplicated paragraphs/list items; nav/footer/scripts removed; plus up to 2 same-domain pages (about/services/products). Truncated to ~12k chars (~3k tokens).
4. **One LLM call** (`analysis_service.py`) returns all five sections as JSON; output is parsed and validated with Pydantic; on failure there is **one repair retry**, then fallback model, then a clean `502`.
5. **Honesty rules**: competitors are labelled `ai_generated_suggestion` (no live market research); services carry `source: website|inferred`; **no search volumes** are produced.

Errors return `{"success": false, "error": {"code", "message"}}`: `invalid_url` / `unsafe_url` (400), `site_blocked` / `no_content` / `invalid_request` (422), `site_unreachable` / `llm_error` / `llm_invalid_output` (502).

Note: JavaScript-rendered sites with little server-side HTML return `no_content`; a headless-browser fallback (Playwright) is the obvious next step.

## Response shape
See `app/schemas.py` (also visible in `/docs`). Top level: `success, website, brand{name,category,summary}, analysis{competitor_analysis, target_search_queries[5], seo_improvements, top_services[≤5], target_audience}, meta{model, cached, latency_ms, input_tokens, output_tokens, pages_analyzed}`.

### Sample request / response (real run, `gemini-3.5-flash-lite`, abridged with `...`)

```bash
curl -X POST http://localhost:4000/link-analysis -H "Content-Type: application/json" -d '{"url": "https://basecamp.com"}'
```
```json
{
  "success": true,
  "website": "https://basecamp.com/",
  "brand": {"name": "Basecamp", "category": "Project Management and Team Collaboration Software", "summary": "..."},
  "analysis": {
    "competitor_analysis": {
      "main_category": "Project Management Software",
      "competitors": [
        {"name": "Asana", "website": "https://asana.com", "target_market": "...", "strengths": ["Advanced workflow builder", "..."],
         "weaknesses": ["Per-user pricing can become expensive", "..."], "source": "ai_generated_suggestion"},
        {"name": "Trello", "...": "..."}, {"name": "Monday.com", "...": "..."}
      ],
      "your_competitive_advantages": ["Fixed-price plans with no per-user fees", "..."]
    },
    "target_search_queries": [
      {"query": "simple project management software no per user fees", "platforms": ["Google", "LinkedIn"], "intent": "Commercial", "...": "..."},
      "... 4 more"
    ],
    "seo_improvements": {
      "primary_keyword": "project management platform",
      "recommended_title": "Basecamp: The Calm, Flat-Fee Project Management Software",
      "meta_description": "Manage projects, communicate company-wide, and work with clients in one place. Enjoy flat-fee pricing with no per-user fees and 24/7 support.",
      "supporting_content": [{"type": "industry page", "title": "Basecamp for Marketing and Creative Agencies", "...": "..."}, "..."]
    },
    "top_services": [{"name": "Project Management", "source": "website", "...": "..."}, "... 4 more"],
    "target_audience": {"primary_audience": ["Small business owners", "Freelancers", "..."], "geographic_focus": "Global", "...": "..."}
  },
  "meta": {"model": "gemini:gemini-3.5-flash-lite", "cached": false, "latency_ms": 7765,
           "input_tokens": 3307, "output_tokens": 2611,
           "pages_analyzed": ["https://basecamp.com/", "https://basecamp.com/pricing", "https://basecamp.com/about"]}
}
```
Add screenshots / logs here: `/docs` page, the terminal output of this request, and error cases (`http://localhost`, `http://169.254.169.254`, `notaurl`).

---

## LLM research: cost, speed, accuracy

**Pricing** is USD per 1M tokens, collected on 18 Nov 2026 from third-party pricing trackers that cite provider pages (several reported figures disagree between sources, and Haiku 5.5's price cut was described as "not yet independently verified"). **Confirm on each official pricing page before relying on them.**

| Provider | Model | Input / Output | Context | JSON support | Notes |
|---|---|---|---|---|---|
| Anthropic | Claude Haiku 5.5 | $0.10 / $0.50 (≤100K prompts) | up to 100K at this price | Prompt-enforced JSON + validation | Cheapest "quality" small model in this set |
| Anthropic | Claude Sonnet 5.5 | $2 / $10 (cached input $0.10) | 1M | Prompt-enforced JSON + validation | Higher-quality fallback |
| OpenAI | GPT-6 Luna | $0.10 / $0.50 | n/a (not verified) | Native `json_object` mode | Same price tier as Haiku 5.5 |
| OpenAI | GPT-6.1 Sol | $2 / $10 | n/a (not verified) | Native `json_object` mode | Mid-tier |
| Google | Gemini 3.8 Flash | $0.75 / $3.75 until 31 Dec 2026, then $1.50 / $7.50 | 1M | Native `responseMimeType: application/json` | Long context |
| Google | Gemini 3.5 Flash-Lite | $0.30 / $2.50 | 1M | Native JSON mode | Budget Google option |

**Measured so far: one run only** (table below). Other models were not benchmarked, and **accuracy was not benchmarked** (only a manual read of one output), so no claim of "maximum accuracy" is made. `scripts/benchmark.py` measures latency, tokens, cost and JSON validity for more models and sites.

| Model | Site | Latency (ms) | In/Out tokens | Cost | Valid JSON | Quality score (manual 1-5) |
|---|---|---|---|---|---|---|
| gemini-3.5-flash-lite | basecamp.com (home + pricing + about) | 7,765 (incl. LLM call only) | 3,307 / 2,611 | $0 (free tier); ≈ $0.0075 at paid rates | valid on first attempt | manual read: services/SEO/audience grounded in site content |

### Cost per analysis
Token usage from the one real run: **3,307 input / 2,611 output**. Costs below apply that usage to list prices (calculated, not billed); other models' token counts may differ slightly.

| Model | Estimated cost / analysis |
|---|---|
| Claude Haiku 5.5 / GPT-6 Luna | ≈ $0.0016 |
| Gemini 3.5 Flash-Lite (paid rates; $0 on free tier) | ≈ $0.0075 |
| Gemini 3.8 Flash (intro price) | ≈ $0.0123 |
| Claude Sonnet 5.5 / GPT-6.1 Sol | ≈ $0.033 |

### Final choice for this project: Google Gemini (free tier only)
The project is configured to use **Gemini only**, because the Gemini API has a free tier.
- **Primary: `gemini-3.5-flash-lite`**, **fallback: `gemini-3.1-flash-lite`** (both set in `.env`). A third-party test on 25 Oct 2026 saw both work on a free-tier key with a 15 requests/minute cap; Google changes free-tier limits and eligible models without notice, so check https://ai.google.dev/gemini-api/docs/rate-limits and set `LLM_MODEL` to any free-eligible model if these stop working.
- **Cost per analysis: $0 on the free tier.** On a paid plan it would be about $0.0075 (calculated from measured tokens). Free-tier data may be used by Google to improve its products, so don't analyze confidential sites.
- **Limits:** about 15 requests/minute and a daily cap; the service retries once after a 429 and then returns a clean `llm_error`. The 1-hour cache avoids repeat calls.
- **JSON:** native `responseMimeType: application/json` plus Pydantic validation and one repair retry.
- **Response time:** 7.8 s on the one measured run (3 pages fetched + 1 LLM call); more runs needed for a typical range.
- **Why not the others for this submission:** Claude Haiku 5.5 / GPT-6 Luna are cheaper per token on paper (~$0.0016/analysis) but have no free API tier; they are kept as optional providers if you later want to compare.
- **Caveat:** Flash-Lite is the smallest tier, so competitor suggestions (from model knowledge) may be less accurate than a larger model's. Run the benchmark and judge quality yourself; do not treat this as the "maximum accuracy" model.

### Cost optimization (implemented ✔ / suggested)
- ✔ Strip scripts/nav/footer/forms, dedupe lines, hard cap at 12k chars
- ✔ One combined call instead of five; compact JSON-shape prompt
- ✔ In-memory TTL cache (1 h) so repeat URLs cost $0
- ✔ Free/small model first, second model only on failure
- Suggested: prompt caching for the static system prompt, Batch API (~50% off) for bulk jobs, Redis/disk cache across restarts, split into a cheap extraction call + a stronger competitor call only if quality requires it

---

## Submission checklist
- [ ] Public GitHub repo, `.env` not committed (`.gitignore` covers it)
- [ ] Real sample request/response, screenshots/logs, benchmark table filled in above
- [ ] Deploy (Render / Railway / Fly.io via the included Dockerfile; set env vars in the host dashboard) and add Live Demo, `/link-analysis` and `/docs` URLs
- [ ] Follow Dxora Technologies on LinkedIn and CREST on Instagram, and include your profile links in the application