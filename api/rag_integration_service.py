"""
RAG Integration Service for OpenNotebook.

Calls the NiemanLocalRag HTTP server (started with `node dist/index.js serve`)
to find documents relevant to a user prompt, which are then added as Sources
to the active notebook.
"""

from dataclasses import dataclass, field
from typing import List, Optional

import httpx
from loguru import logger


@dataclass
class RagResult:
    """A single result returned by the RAG query endpoint."""

    file_path: str
    chunk_index: int
    text: str
    score: float
    file_title: Optional[str] = None
    source: Optional[str] = None  # set for ingest_data items (URLs, etc.)


@dataclass
class RagFileEntry:
    file_path: str
    ingested: bool
    chunk_count: Optional[int] = None
    timestamp: Optional[str] = None


class RagIntegrationService:
    """HTTP client for the NiemanLocalRag HTTP server."""

    def __init__(self, base_url: str = "http://host.docker.internal:3001", timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def is_available(self) -> bool:
        """Return True if the RAG HTTP server responds to /health."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def query(self, query: str, limit: int = 10) -> List[RagResult]:
        """Semantic search: return up to `limit` relevant document chunks."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    f"{self.base_url}/query",
                    json={"query": query, "limit": limit},
                )
                resp.raise_for_status()
                data = resp.json()
                results: List[RagResult] = []
                for item in data if isinstance(data, list) else []:
                    results.append(
                        RagResult(
                            file_path=item.get("filePath", item.get("file_path", "")),
                            chunk_index=item.get("chunkIndex", item.get("chunk_index", 0)),
                            text=item.get("text", ""),
                            score=item.get("score", 0.0),
                            file_title=item.get("fileTitle", item.get("file_title")),
                            source=item.get("source"),
                        )
                    )
                return results
        except Exception as e:
            logger.error(f"RAG query failed: {e}")
            raise

    async def list_files(self) -> List[RagFileEntry]:
        """Return all files known to the RAG vector store."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/list")
                resp.raise_for_status()
                data = resp.json()
                files = data if isinstance(data, list) else data.get("files", [])
                return [
                    RagFileEntry(
                        file_path=f.get("filePath", f.get("file_path", "")),
                        ingested=f.get("ingested", False),
                        chunk_count=f.get("chunkCount", f.get("chunk_count")),
                        timestamp=f.get("timestamp"),
                    )
                    for f in files
                ]
        except Exception as e:
            logger.error(f"RAG list_files failed: {e}")
            raise

    async def ingest_path(self, file_path: str) -> dict:
        """Ingest a file or directory into the RAG vector store.

        Always uses /ingest-dir which handles both single files and directories
        (avoids Docker path resolution issues for host filesystem paths).
        """
        try:
            async with httpx.AsyncClient(timeout=300.0) as client:
                resp = await client.post(
                    f"{self.base_url}/ingest-dir",
                    json={"dirPath": file_path},
                )
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"RAG ingest_path failed for {file_path}: {e}")
            raise

    async def status(self) -> dict:
        """Get RAG server status (total docs, chunks, db size, etc.)."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/status")
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"RAG status failed: {e}")
            raise


# Module-level instance (re-created if URL changes)
_rag_service_instance: Optional[RagIntegrationService] = None


def get_rag_service(base_url: str = "http://host.docker.internal:3001") -> RagIntegrationService:
    """Return (or create) the singleton RAG service pointing at base_url."""
    global _rag_service_instance
    if _rag_service_instance is None or _rag_service_instance.base_url != base_url.rstrip("/"):
        _rag_service_instance = RagIntegrationService(base_url=base_url)
    return _rag_service_instance
