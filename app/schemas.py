from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

PLATFORMS = ["Google", "Facebook", "Instagram", "LinkedIn", "X"]


class AnalyzeRequest(BaseModel):
    url: str = Field(..., examples=["https://example.com"])


class Brand(BaseModel):
    name: str = ""
    category: str = ""
    summary: str = ""


class Competitor(BaseModel):
    name: str
    website: str = ""
    main_service: str = ""
    target_market: str = ""
    strengths: list[str] = []
    weaknesses: list[str] = []
    key_strength: str = ""
    opportunity_for_your_brand: str = ""
    source: Literal["ai_generated_suggestion"] = "ai_generated_suggestion"


class CompetitorAnalysis(BaseModel):
    brand_overview: str = ""
    main_category: str = ""
    main_products_services: list[str] = []
    competitors: list[Competitor] = []
    your_competitive_advantages: list[str] = []
    positioning_opportunities: list[str] = []
    note: str = (
        "Competitors are AI-generated suggestions based on the website content, "
        "not verified market research."
    )


class SearchQuery(BaseModel):
    query: str
    platforms: list[str]
    intent: str = ""
    business_relevance: str = ""
    target_audience: str = ""

    @field_validator("platforms")
    @classmethod
    def _norm_platforms(cls, v: list[str]) -> list[str]:
        out = []
        for p in v:
            low = p.strip().lower()
            name = ("X" if low.startswith(("x", "twitter")) else
                    next((c for c in PLATFORMS if c.lower() == low), None))
            if name and name not in out:
                out.append(name)
        return out or ["Google"]


class SupportContent(BaseModel):
    type: str  # landing page | FAQ | blog | location page | industry page ...
    title: str
    reason: str = ""


class SEOImprovements(BaseModel):
    primary_keyword: str = ""
    secondary_keywords: list[str] = []
    long_tail_keywords: list[str] = []
    business_keywords: list[str] = []
    recommended_title: str = ""
    title_rationale: str = ""
    meta_description: str = ""
    supporting_content: list[SupportContent] = []
    note: str = "No search-volume or ranking data is included; none was sourced from a data provider."


class Service(BaseModel):
    name: str
    description: str = ""
    target_industry: str = ""
    target_customer: str = ""
    main_benefit: str = ""
    source: Literal["website", "inferred"] = "website"


class AudienceSegment(BaseModel):
    audience: str
    business_type: str = ""
    requirement: str = ""


class TargetAudience(BaseModel):
    primary_audience: list[str] = []
    secondary_audience: list[str] = []
    industries: list[str] = []
    business_types: list[str] = []
    customer_profiles: list[str] = []
    geographic_focus: str = ""
    customer_needs: list[str] = []
    customer_interests: list[str] = []
    recommended_marketing_segments: list[AudienceSegment] = []


class Analysis(BaseModel):
    competitor_analysis: CompetitorAnalysis
    target_search_queries: list[SearchQuery]
    seo_improvements: SEOImprovements
    top_services: list[Service]
    target_audience: TargetAudience

    @model_validator(mode="after")
    def _check(self):
        self.top_services = self.top_services[:5]
        self.target_search_queries = self.target_search_queries[:5]
        if len(self.target_search_queries) != 5:
            raise ValueError("exactly 5 target_search_queries are required")
        if not self.top_services:
            raise ValueError("top_services must not be empty")
        return self


class LLMResult(BaseModel):
    brand: Brand
    analysis: Analysis


class Meta(BaseModel):
    model: str
    cached: bool = False
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    pages_analyzed: list[str] = []


class AnalyzeResponse(BaseModel):
    success: bool = True
    website: str
    brand: Brand
    analysis: Analysis
    meta: Meta
