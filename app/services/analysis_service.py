"""Orchestrates: validate -> extract -> LLM -> validate output -> response."""
import time

from pydantic import ValidationError

from app.config import get_settings
from app.schemas import AnalyzeResponse, LLMResult, Meta
from app.services import competitor_service, llm_service, website_extractor
from app.utils.validators import assert_public_host, normalize_url

_CACHE: dict[str, tuple[float, AnalyzeResponse]] = {}

SYSTEM = """You are a senior marketing and SEO analyst. Analyze ONLY the website content provided.
Rules:
- Ground every statement in the content; do not invent facts about the brand. Use "" or [] when unknown.
- Competitors are your own suggestions from general knowledge (3-5 real, relevant companies). Never include the analyzed brand itself.
- Do NOT give search volumes, rankings or traffic numbers.
- top_services: the 5 most important services/products found on the site. Set source="website" if explicitly present, else "inferred".
- target_search_queries: exactly 5, each with 1-3 suitable platforms from [Google, Facebook, Instagram, LinkedIn, X].
- recommended_title <= 60 chars, meta_description <= 155 chars.
- Reply with a single valid JSON object only. No markdown, no commentary."""

SCHEMA_HINT = """JSON shape:
{"brand":{"name":"","category":"","summary":""},
"analysis":{
 "competitor_analysis":{"brand_overview":"","main_category":"","main_products_services":[],
   "competitors":[{"name":"","website":"","main_service":"","target_market":"","strengths":[],"weaknesses":[],"key_strength":"","opportunity_for_your_brand":""}],
   "your_competitive_advantages":[],"positioning_opportunities":[]},
 "target_search_queries":[{"query":"","platforms":[],"intent":"","business_relevance":"","target_audience":""}],
 "seo_improvements":{"primary_keyword":"","secondary_keywords":[],"long_tail_keywords":[],"business_keywords":[],
   "recommended_title":"","title_rationale":"","meta_description":"",
   "supporting_content":[{"type":"service landing page|industry page|FAQ|blog|location page|article","title":"","reason":""}]},
 "top_services":[{"name":"","description":"","target_industry":"","target_customer":"","main_benefit":"","source":"website|inferred"}],
 "target_audience":{"primary_audience":[],"secondary_audience":[],"industries":[],"business_types":[],"customer_profiles":[],
   "geographic_focus":"","customer_needs":[],"customer_interests":[],
   "recommended_marketing_segments":[{"audience":"","business_type":"","requirement":""}]}}}"""


class OutputError(Exception):
    pass


async def _call_and_validate(user: str, provider: str, model: str):
    reply = await llm_service.generate(SYSTEM, user, provider, model)
    try:
        return reply, LLMResult.model_validate(llm_service.parse_json(reply.text))
    except (ValueError, ValidationError) as first_err:
        # One repair attempt: show the model its own error.
        fix = f"{user}\n\nYour previous reply was invalid ({str(first_err)[:400]}). Return corrected JSON only."
        reply = await llm_service.generate(SYSTEM, fix, provider, model)
        try:
            return reply, LLMResult.model_validate(llm_service.parse_json(reply.text))
        except (ValueError, ValidationError) as e:
            raise OutputError(str(e)[:200])


async def analyze(raw_url: str) -> AnalyzeResponse:
    s = get_settings()
    url = normalize_url(raw_url)
    await assert_public_host(url)

    hit = _CACHE.get(url)
    if hit and time.time() - hit[0] < s.cache_ttl_s:
        cached = hit[1].model_copy(deep=True)
        cached.meta.cached = True
        return cached

    final_url, content, pages = await website_extractor.extract_website(url)
    user = f"Website: {final_url}\n\n<website_content>\n{content}\n</website_content>\n\n{SCHEMA_HINT}"

    try:
        reply, result = await _call_and_validate(user, s.llm_provider, s.llm_model)
    except (llm_service.LLMError, OutputError):
        if (s.fallback_provider, s.fallback_model) == (s.llm_provider, s.llm_model):
            raise
        reply, result = await _call_and_validate(user, s.fallback_provider, s.fallback_model)

    ca = result.analysis.competitor_analysis
    ca.competitors = competitor_service.clean_competitors(ca.competitors, result.brand.name, final_url)

    resp = AnalyzeResponse(
        website=final_url, brand=result.brand, analysis=result.analysis,
        meta=Meta(model=f"{reply.provider}:{reply.model}", latency_ms=reply.latency_ms,
                  input_tokens=reply.input_tokens, output_tokens=reply.output_tokens, pages_analyzed=pages),
    )
    _CACHE[url] = (time.time(), resp)
    return resp
