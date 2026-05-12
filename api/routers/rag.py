"""
RAG Integration router — management endpoints for the NiemanLocalRag HTTP service.

Endpoints:
  GET  /api/rag/status  — check service health + stats
  POST /api/rag/query   — manual semantic search (for testing)
  POST /api/rag/ingest  — trigger ingestion of a file/path
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from loguru import logger
from pydantic import BaseModel

from api.rag_integration_service import RagResult, get_rag_service
from open_notebook.domain.content_settings import ContentSettings

router = APIRouter()


# ── Request / Response models ────────────────────────────────────────────────

class RagQueryRequest(BaseModel):
    query: str
    limit: Optional[int] = 10


class RagQueryResultItem(BaseModel):
    file_path: str
    chunk_index: int
    text: str
    score: float
    file_title: Optional[str] = None
    source: Optional[str] = None


class RagIngestRequest(BaseModel):
    file_path: str


class RagStatusResponse(BaseModel):
    available: bool
    details: Optional[dict] = None
    rag_enabled: bool = False
    rag_service_url: str = "http://host.docker.internal:3001"


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get_rag_url() -> str:
    settings: ContentSettings = await ContentSettings.get_instance()  # type: ignore[assignment]
    return settings.rag_service_url or "http://host.docker.internal:3001"


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/rag/status", response_model=RagStatusResponse)
async def rag_status(url: Optional[str] = Query(default=None)):
    """Check whether the RAG HTTP service is reachable and return its stats.

    If `url` is provided, it is tested directly (useful for the settings form
    before saving). Otherwise the saved settings URL is used.
    """
    try:
        settings: ContentSettings = await ContentSettings.get_instance()  # type: ignore[assignment]
        saved_url = settings.rag_service_url or "http://host.docker.internal:3001"
        test_url = url or saved_url
        svc = get_rag_service(test_url)
        available = await svc.is_available()
        details = None
        if available:
            try:
                details = await svc.status()
            except Exception:
                pass
        return RagStatusResponse(
            available=available,
            details=details,
            rag_enabled=settings.rag_enabled or False,
            rag_service_url=test_url,
        )
    except Exception as e:
        logger.error(f"RAG status check failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag/query", response_model=List[RagQueryResultItem])
async def rag_query(request: RagQueryRequest):
    """Manually query the RAG service (useful for testing)."""
    try:
        url = await _get_rag_url()
        svc = get_rag_service(url)
        results = await svc.query(request.query, limit=request.limit or 10)
        return [
            RagQueryResultItem(
                file_path=r.file_path,
                chunk_index=r.chunk_index,
                text=r.text,
                score=r.score,
                file_title=r.file_title,
                source=r.source,
            )
            for r in results
        ]
    except Exception as e:
        logger.error(f"RAG query endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/rag/ingest")
async def rag_ingest(request: RagIngestRequest):
    """Trigger ingestion of a file or directory into the RAG vector store."""
    try:
        url = await _get_rag_url()
        svc = get_rag_service(url)
        result = await svc.ingest_path(request.file_path)
        return {"success": True, "result": result}
    except Exception as e:
        logger.error(f"RAG ingest endpoint error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
