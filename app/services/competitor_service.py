"""Post-processing for LLM-suggested competitors (no live market data is used)."""
import re
from urllib.parse import urlsplit

from app.schemas import Competitor


def clean_competitors(competitors: list[Competitor], brand_name: str, site_url: str) -> list[Competitor]:
    host = (urlsplit(site_url).hostname or "").removeprefix("www.")
    brand = re.sub(r"\W+", "", brand_name.lower())
    seen, out = set(), []
    for c in competitors:
        key = re.sub(r"\W+", "", c.name.lower())
        own = key == brand or (host and host in c.website.lower())
        if not key or key in seen or own:
            continue
        seen.add(key)
        out.append(c)
    return out[:5]
