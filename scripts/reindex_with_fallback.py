#!/usr/bin/env python3
"""Reindex existing DB by adding documents that were skipped because <CONTENU> was empty.

Strategy (incremental / safe):
- Scan archives
- For each XML:
  - If already in documents table: skip
  - Else parse XML and extract text using fallback (CONTENU then itertext)
  - If extracted text length >= threshold: insert doc+page

This lets you recover Case C documents without rebuilding whole DB.

Usage:
  cd docs/Legifrance
  python scripts/reindex_with_fallback.py --index-name jorf_prod --source JORF --threshold 500 --max-inserts 50000
"""
import sys
import argparse
import json
import time
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from archive_scanner import scan_archives, stream_archive
from db_manager import DBManager
from xml_parser import parse_legifrance_xml, XMLParseError
from xml_text_fallback import extract_text_with_fallback


def main():
    parser = argparse.ArgumentParser(description="Reindex missing docs using itertext fallback")
    parser.add_argument("--index-name", required=True, help="Existing index name (e.g., jorf_prod)")
    parser.add_argument("--source", required=True, help="Source folder under archives/ (e.g., JORF, LEGI, CNIL)")
    parser.add_argument("--threshold", type=int, default=500, help="Min extracted text length to insert")
    parser.add_argument("--max-inserts", type=int, default=100000, help="Safety cap")
    parser.add_argument("--only-freemium", action="store_true")
    parser.add_argument("--only-incremental", action="store_true")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    base = Path(__file__).parent.parent
    db_path = base / "sqlite3" / f"index_{args.index_name}.db"
    if not db_path.exists():
        print(json.dumps({"status": "error", "error": f"DB not found: {db_path}"}))
        sys.exit(2)

    archives_root = base / "archives" / args.source.upper()
    if args.only_freemium and args.only_incremental:
        print(json.dumps({"status": "error", "error": "choose only one of --only-freemium / --only-incremental"}))
        sys.exit(2)

    if args.only_freemium:
        scan_root = archives_root / "freemium"
    elif args.only_incremental:
        scan_root = archives_root / "incremental"
    else:
        scan_root = archives_root

    if not scan_root.exists():
        print(json.dumps({"status": "error", "error": f"scan_root not found: {scan_root}"}))
        sys.exit(2)

    start = time.time()
    inserted = 0
    already = 0
    parse_errors = 0
    empty_after_fallback = 0

    BATCH = 500
    docs_batch = []
    pages_batch = []

    now = int(time.time())

    def flush(db: DBManager):
        nonlocal docs_batch, pages_batch
        if not docs_batch:
            return
        db.executemany(
            """INSERT OR IGNORE INTO documents 
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
        page_tuples = []
        for p in pages_batch:
            doc_id = doc_ids.get(p["xml_path"])
            if not doc_id:
                continue
            page_tuples.append((doc_id, 1, p["content"], p["content_length"], p["content"], 0, None))
        if page_tuples:
            db.executemany(
                """INSERT OR IGNORE INTO pages 
                   (doc_id, page_number, content, content_length, content_stem, was_ocr, ocr_confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                page_tuples,
            )
        db.commit()
        docs_batch = []
        pages_batch = []

    with DBManager(db_path) as db:
        for archive_info in scan_archives(scan_root):
            for xml_info in stream_archive(archive_info["archive_path"]):
                if inserted >= args.max_inserts:
                    break

                xml_path = xml_info["xml_path"]

                # already indexed?
                row = db.query_one("SELECT 1 as ok FROM documents WHERE path = ?", (xml_path,))
                if row:
                    already += 1
                    continue

                xml_bytes = xml_info["xml_content"]

                try:
                    parsed = parse_legifrance_xml(xml_bytes)
                except XMLParseError:
                    parse_errors += 1
                    continue

                # Fallback extraction
                try:
                    full_text = extract_text_with_fallback(xml_bytes)
                except Exception:
                    parse_errors += 1
                    continue

                if len(full_text.strip()) < args.threshold:
                    empty_after_fallback += 1
                    continue

                content_hash = hashlib.sha256(xml_bytes).hexdigest()

                docs_batch.append((
                    xml_path,
                    "xml",
                    "french",
                    1,
                    xml_info["size"],
                    int(xml_info["mtime"]),
                    now,
                    content_hash,
                    xml_info["archive_name"],
                    xml_path,
                    parsed.get("xml_id") or xml_info.get("xml_id"),
                    parsed.get("nature"),
                    parsed.get("juridiction"),
                    parsed.get("date_decision"),
                    "{}",
                ))

                pages_batch.append({
                    "xml_path": xml_path,
                    "content": full_text,
                    "content_length": len(full_text),
                })

                inserted += 1

                if args.verbose and inserted % 1000 == 0:
                    print(f"inserted={inserted} already={already} parse_errors={parse_errors} low_text={empty_after_fallback}")

                if len(docs_batch) >= BATCH:
                    flush(db)

            if inserted >= args.max_inserts:
                break

        flush(db)

        # rebuild FTS
        db.execute("INSERT INTO content_fts(content_fts) VALUES ('rebuild')")
        db.commit()

    dur = time.time() - start
    out = {
        "status": "completed",
        "index_name": args.index_name,
        "source": args.source.upper(),
        "scan_root": str(scan_root),
        "inserted": inserted,
        "already_present": already,
        "parse_errors": parse_errors,
        "skipped_low_text": empty_after_fallback,
        "duration_seconds": round(dur, 2),
        "speed_inserts_per_sec": round(inserted / dur, 2) if dur > 0 else None,
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
