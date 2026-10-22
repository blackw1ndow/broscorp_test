"""Indexes the «Лісовий архів» folder at startup (R6). Idempotent: files are keyed by SHA-256.

Uses no LLM calls, so the free Groq quota is left for the animals' questions.
"""

import asyncio
import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg

from forest_bot.config import ARCHIVE_UPLOADED_AT
from forest_bot.db.repositories import documents
from forest_bot.embeddings import Embedder
from forest_bot.ingestion.chunking import chunk_text
from forest_bot.ingestion.extract import SUPPORTED_EXTENSIONS, extract_text
from forest_bot.ingestion.placement import detect_place, document_type

log = logging.getLogger(__name__)


@dataclass
class SeedReport:
    indexed: list[str] = field(default_factory=list)
    already_indexed: int = 0
    failed: list[str] = field(default_factory=list)


async def seed_archive(pool: asyncpg.Pool, embedder: Embedder, archive_dir: Path) -> SeedReport:
    report = SeedReport()
    async with pool.acquire() as conn:
        known = await documents.archive_hashes(conn)

    for path in await asyncio.to_thread(_archive_files, archive_dir):
        data = await asyncio.to_thread(path.read_bytes)
        sha256 = hashlib.sha256(data).hexdigest()
        if sha256 in known:
            report.already_indexed += 1
            continue
        try:
            await _index_file(pool, embedder, path, data, sha256)
        except Exception:
            log.exception("Failed to index archive file %s", path.name)
            report.failed.append(path.name)
        else:
            report.indexed.append(path.name)

    log.info(
        "Archive: %d indexed, %d already indexed, %d failed %s",
        len(report.indexed),
        report.already_indexed,
        len(report.failed),
        report.failed or "",
    )
    return report


def _archive_files(archive_dir: Path) -> list[Path]:
    return sorted(p for p in archive_dir.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS)


async def _index_file(
    pool: asyncpg.Pool, embedder: Embedder, path: Path, data: bytes, sha256: str
) -> None:
    extracted = await asyncio.to_thread(extract_text, path.name, data)
    if not extracted.text:
        raise ValueError("no text extracted")

    # Archive file names are the documents' titles; PDF headings may be split across lines
    title = path.stem
    placement = detect_place(title, extracted.text)
    if placement.place is None:
        raise ValueError(f"place not detected, candidates: {placement.conflicting}")

    chunks = chunk_text(title, extracted.text)
    embeddings = await embedder.embed(chunks)
    doc = documents.NewDocument(
        title=title,
        doc_type=document_type(title, placement.place),
        place_code=placement.place.code,
        source="archive",
        author_id=None,
        file_name=path.name,
        file_sha256=sha256,
        extraction=extracted.method.value,
        full_text=extracted.text,
        uploaded_at=ARCHIVE_UPLOADED_AT,
    )
    async with pool.acquire() as conn, conn.transaction():
        await documents.insert_document(conn, doc, chunks, embeddings)
    log.info("Indexed %s -> %s (%s)", path.name, placement.place.name, extracted.method.value)
