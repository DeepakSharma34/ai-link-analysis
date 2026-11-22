"""Measure latency/tokens/cost per model on real sites.
Usage: python -m scripts.benchmark https://site1 https://site2
Update MODELS/PRICES (USD per 1M tokens) after checking each provider's pricing page."""
import asyncio
import sys

from app.schemas import LLMResult
from app.services import analysis_service as a, llm_service, website_extractor

MODELS = [("gemini", "gemini-3.5-flash-lite"), ("gemini", "gemini-3.1-flash-lite")]
PRICES = {"gemini-3.5-flash-lite": (0.0, 0.0), "gemini-3.1-flash-lite": (0.0, 0.0)}  # free tier; paid: 0.30/2.50 and 0.25/1.50


async def main(urls):
    for url in urls:
        final, text, _ = await website_extractor.extract_website(url)
        user = f"Website: {final}\n\n<website_content>\n{text}\n</website_content>\n\n{a.SCHEMA_HINT}"
        for prov, model in MODELS:
            try:
                r = await llm_service.generate(a.SYSTEM, user, prov, model)
                LLMResult.model_validate(llm_service.parse_json(r.text))
                ok = "valid"
            except Exception as e:
                print(f"{url} | {model} | INVALID/ERROR ({type(e).__name__})")
                continue
            pi, po = PRICES.get(model, (0, 0))
            cost = (r.input_tokens * pi + r.output_tokens * po) / 1e6
            print(f"{url} | {model} | {r.latency_ms} ms | in {r.input_tokens} out {r.output_tokens} | ${cost:.4f} | {ok}")


asyncio.run(main(sys.argv[1:]))
