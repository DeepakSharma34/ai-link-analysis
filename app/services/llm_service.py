"""Thin provider-agnostic LLM client (Anthropic / OpenAI / Gemini) over httpx."""
import asyncio
import json
import re
import time
from dataclasses import dataclass

import httpx

from app.config import get_settings


class LLMError(Exception):
    pass


@dataclass
class LLMReply:
    text: str
    provider: str
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None


def _ok(r: httpx.Response) -> dict:
    if r.status_code == 429:
        raise LLMError("rate_limited")
    if r.status_code >= 400:
        raise LLMError(f"LLM API returned HTTP {r.status_code}")  # body not echoed (may contain secrets)
    return r.json()


async def generate(system: str, user: str, provider: str, model: str, max_tokens: int = 4000) -> LLMReply:
    try:
        return await _generate(system, user, provider, model, max_tokens)
    except LLMError as e:
        if "rate_limited" not in str(e):
            raise
        await asyncio.sleep(20)  # free tier: per-minute limit clears quickly; retry once
        return await _generate(system, user, provider, model, max_tokens)


async def _generate(system: str, user: str, provider: str, model: str, max_tokens: int = 4000) -> LLMReply:
    s = get_settings()
    start = time.perf_counter()
    async with httpx.AsyncClient(timeout=s.llm_timeout_s) as c:
        try:
            if provider == "anthropic":
                r = await c.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01"},
                    json={"model": model, "max_tokens": max_tokens, "system": system,
                          "messages": [{"role": "user", "content": user}]},
                )
                d = _ok(r)
                text = "".join(b.get("text", "") for b in d["content"])
                usage = (d["usage"]["input_tokens"], d["usage"]["output_tokens"])
            elif provider == "openai":
                r = await c.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {s.openai_api_key}"},
                    json={"model": model, "max_completion_tokens": max_tokens,
                          "response_format": {"type": "json_object"},
                          "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
                )
                d = _ok(r)
                text = d["choices"][0]["message"]["content"]
                usage = (d["usage"]["prompt_tokens"], d["usage"]["completion_tokens"])
            elif provider == "gemini":
                r = await c.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": s.gemini_api_key},
                    json={"systemInstruction": {"parts": [{"text": system}]},
                          "contents": [{"role": "user", "parts": [{"text": user}]}],
                          "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": max_tokens}},
                )
                d = _ok(r)
                text = "".join(p.get("text", "") for p in d["candidates"][0]["content"]["parts"])
                u = d.get("usageMetadata", {})
                usage = (u.get("promptTokenCount"), u.get("candidatesTokenCount"))
            else:
                raise LLMError(f"Unknown provider '{provider}'.")
        except (httpx.HTTPError, KeyError, IndexError) as e:
            raise LLMError(f"{provider} request failed: {type(e).__name__}") from e
    return LLMReply(text, provider, model, int((time.perf_counter() - start) * 1000), *usage)


def parse_json(text: str) -> dict:
    """Extract the first JSON object from a reply (tolerates ```json fences / stray prose)."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])
