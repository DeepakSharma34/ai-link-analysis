from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.schemas import AnalyzeRequest, AnalyzeResponse
from app.services import analysis_service, llm_service
from app.services.website_extractor import FetchError
from app.utils.validators import InvalidURLError, UnsafeURLError

app = FastAPI(title="AI Link Analysis", version="1.0.0",
              description="Analyze a website URL with an LLM: competitors, search queries, SEO, services, audience.")


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"success": False, "error": {"code": code, "message": message}})


@app.exception_handler(RequestValidationError)
async def _validation(_, exc):
    return _err(422, "invalid_request", 'Request body must be JSON like {"url": "https://example.com"}.')


@app.exception_handler(InvalidURLError)
async def _invalid(_, exc):
    return _err(400, "invalid_url", str(exc))


@app.exception_handler(UnsafeURLError)
async def _unsafe(_, exc):
    return _err(400, "unsafe_url", str(exc))


@app.exception_handler(FetchError)
async def _fetch(_, exc: FetchError):
    status = {"site_blocked": 422, "no_content": 422}.get(exc.code, 502)
    return _err(status, exc.code, exc.message)


@app.exception_handler(llm_service.LLMError)
async def _llm(_, exc):
    return _err(502, "llm_error", "The LLM provider failed or is unavailable. Please retry.")


@app.exception_handler(analysis_service.OutputError)
async def _output(_, exc):
    return _err(502, "llm_invalid_output", "The LLM returned output that failed validation. Please retry.")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/link-analysis", response_model=AnalyzeResponse)
async def link_analysis(body: AnalyzeRequest):
    return await analysis_service.analyze(body.url)
