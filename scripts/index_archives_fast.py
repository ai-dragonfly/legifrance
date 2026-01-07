#!/usr/bin/env python3
"""Index Legifrance archives (OPTIMIZED for speed) - WITH TEXT FALLBACK.

Key changes vs previous version:
- Text extraction: <CONTENU> first, then itertext() fallback
  => recovers documents that were previously skipped (Case C).

Optimizations kept:
- Batch inserts
- PRAGMA tuning
- FTS5 rebuild at end

Usage:
  cd docs/Legifrance
  python scripts/index_archives_fast.py --index-name legi_prod --archives-root archives/LEGI --verbose
"""
import sys
import argparse
import json
import time
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from archive_scanner import scan_archives, stream_archive
from db_manager import DBManager, create_legifrance_index
from xml_parser import parse_legifrance_xml, XMLParseError
from xml_text_fallback import extract_text_with_fallback


SKIP_BASENAMES = {
    # often structural/technical
    "versions.xml",
}


def index_archives_fast(index_name: str, archives_root: Path, sources=None, verbose=False, threshold=1) -> dict:
    start_time = time.time()

    db_root = Path(__file__).parent.parent / "sqlite3"
    db_root.mkdir(exist_ok=True)
    db_path = db_root / f"index_{index_name}.db"

    if db_path.exists():
        return {
            "operation": "index",
            "status": "error",
            "error": f"Index '{index_name}' already exists",
            "index_name": index_name,
        }

    if verbose:
        print(f"Creating index: {index_name}")
    create_legifrance_index(db_path)

    now = int(time.time())

    # Fast PRAGMAs during indexing
    with DBManager(db_path) as db:
        db.execute("PRAGMA journal_mode=MEMORY")
        db.execute("PRAGMA synchronous=OFF")
        db.execute("PRAGMA cache_size=10000")
        db.execute("PRAGMA temp_store=MEMORY")

        db.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("mode", "fast"))
        db.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("created_at", str(now)))
        db.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("indexed_at", str(now)))
        db.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("version", "2.1.0-xml-fallback"))
        db.commit()

    BATCH_SIZE = 1000
    docs_batch = []
    pages_batch = []

    archives_processed = 0
    files_seen = 0
    files_indexed = 0
    skipped_low_text = 0
    skipped_technical = 0
    errors = []

    with DBManager(db_path) as db:
        for archive_info in scan_archives(archives_root, sources):
            if verbose:
                print(f"\nProcessing: {archive_info['archive_name']}")
            archives_processed += 1

            for xml_info in stream_archive(archive_info["archive_path"]):
                files_seen += 1

                # skip technical basenames (optional)
                if Path(xml_info["xml_path"]).name in SKIP_BASENAMES:
                    skipped_technical += 1
                    continue

                xml_bytes = xml_info["xml_content"]

                try:
                    parsed = parse_legifrance_xml(xml_bytes)
                except XMLParseError as e:
                    errors.append(f"{xml_info['xml_path']}: {e}")
                    continue
                except Exception as e:
                    errors.append(f"{xml_info['xml_path']}: {e}")
                    continue

                # NEW: fallback extraction
                try:
                    content = extract_text_with_fallback(xml_bytes)
                except Exception as e:
                    errors.append(f"{xml_info['xml_path']}: fallback_extract_error: {e}")
                    continue

                if len(content.strip()) < threshold:
                    skipped_low_text += 1
                    continue

                content_hash = hashlib.sha256(xml_bytes).hexdigest()

                docs_batch.append(
                    (
                        xml_info["xml_path"],
                        "xml",
                        "french",
                        1,
                        xml_info["size"],
                        xml_info["mtime"],
                        now,
                        content_hash,
                        xml_info["archive_name"],
                        xml_info["xml_path"],
                        parsed.get("xml_id") or xml_info.get("xml_id"),
                        parsed.get("nature") or "",
                        parsed.get("juridiction"),
                        parsed.get("date_decision"),
                        "{}",
                    )
                )

                pages_batch.append(
                    {
                        "xml_path": xml_info["xml_path"],
                        "content": content,
                        "content_length": len(content),
                    }
                )

                files_indexed += 1

                if len(docs_batch) >= BATCH_SIZE:
                    _flush_batches(db, docs_batch, pages_batch, verbose)
                    docs_batch = []
                    pages = []

        if docs_batch:
            _flush_batches(db, docs_batch, pages_batch, verbose)

        db.commit()

        if verbose:
            print("\nRebuilding FTS5 index...")
        db.execute("INSERT INTO content_fts(content_fts) VALUES ('rebuild')")
        db.commit()

        # Restore normal PRAGMAs
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
        db.commit()

    duration = time.time() - start_time

    if verbose:
        print(f"\n✓ Completed in {duration:.1f}s")
        if duration > 0:
            print(f"  Indexed speed: {files_indexed/duration:.0f} docs/sec")
        print(f"  Archives: {archives_processed}")
        print(f"  XML seen: {files_seen}")
        print(f"  Docs indexed: {files_indexed}")
        print(f"  Skipped low-text: {skipped_low_text}")
        print(f"  Skipped technical: {skipped_technical}")
        if errors:
            print(f"  Errors: {len(errors)} (showing first 10)")

    return {
        "operation": "index",
        "status": "completed",
        "index_name": index_name,
        "archives_processed": archives_processed,
        "xml_seen": files_seen,
        "docs_indexed": files_indexed,
        "skipped_low_text": skipped_low_text,
        "skipped_technical": skipped_technical,
        "duration_seconds": round(duration, 2),
        "speed_docs_per_sec": round(files_indexed / duration, 2) if duration > 0 else None,
        "errors": errors[:10],
    }


def _flush_batches(db: DBManager, docs_batch, pages_batch, verbose):
    if not docs_batch:
        return

    db.executemany(
        """INSERT OR REPLACE INTO documents 
           (path, file_type, language, page_count, size, modified_at, indexed_at,
            content_hash, archive_name, xml_path, xml_id, nature, juridiction, 
            date_decision, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        docs_batch,
    )

    # map ids
    doc_ids = {}
    for d in docs_batch:
        xml_path = d[0]
        row = db.query_one("SELECT id FROM documents WHERE path = ?", (xml_path,))
        if row:
            doc_ids[xml_path] = row["id"]

    pages_tuples = []
    for p in pages_batch:
        doc_id = doc_ids.get(p["xml_path"])
        if not doc_id:
            continue
        pages_tuples.append((doc_id, 1, p["content"], p["content_length"], p["content"], 0, None))

    if pages_tuples:
        db.executemany(
            """INSERT OR REPLACE INTO pages 
               (doc_id, page_number, content, content_length, content_stem, was_ocr, ocr_confidence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            pages_tuples,
        )

    db.commit()

    if verbose:
        print(f"  Flushed batch: {len(docs_batch)} docs", end="\r")


def main():
    parser = argparse.ArgumentParser(description="Index Legifrance archives (FAST, with fallback)")
    parser.add_argument("--index-name", required=True)
    parser.add_argument("--archives-root", required=True)
    parser.add_argument("--sources", help="Filter sources (comma-separated)")
    parser.add_argument("--threshold", type=int, default=1, help="Min extracted text length to index")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    archives_root = Path(args.archives_root).resolve()
    if not archives_root.exists():
        print(json.dumps({"status": "error", "error": f"Archives root not found: {archives_root}"}))
        sys.exit(2)

    sources = args.sources.split(",") if args.sources else None

    result = index_archives_fast(
        args.index_name,
        archives_root,
        sources=sources,
        verbose=args.verbose,
        threshold=args.threshold,
    )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result.get("status") == "completed" else 1)


if __name__ == "__main__":
    main()
