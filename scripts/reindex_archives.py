#!/usr/bin/env python3
"""Reindex Legifrance archives incrementally (SAFE).

Goal:
- Process archives in chronological order
- For each XML:
  - If not in DB: insert
  - If in DB but content changed (hash differs): update

This is the daily script to run after downloading new archives.

Usage:
  cd docs/legifrance-indexer
  python scripts/reindex_archives.py --index-name jorf_prod --archives-root archives/JORF --verbose

Notes:
- No extraction to disk (stream tar.gz)
- Uses content_hash (sha256(xml_content)) for delta detection
- Keeps FTS5 updated via triggers on pages table
"""
import sys
import argparse
import json
import time
import hashlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from archive_scanner import scan_archives, stream_archive
from xml_parser import parse_legifrance_xml, XMLParseError
from db_manager import DBManager


def _db_path(index_name: str) -> Path:
    base = Path(__file__).parent.parent
    return base / "sqlite3" / f"index_{index_name}.db"


def _get_existing_hash(db: DBManager, xml_path: str):
    row = db.query_one("SELECT content_hash FROM documents WHERE path = ?", (xml_path,))
    return row.get("content_hash") if row else None


def reindex_archives(index_name: str, archives_root: Path, sources=None, verbose=False, force=False) -> dict:
    start_time = time.time()
    db_path = _db_path(index_name)

    if not db_path.exists():
        return {
            "operation": "reindex",
            "status": "error",
            "error": f"Index '{index_name}' not found (DB missing: {db_path}). Use index_archives_fast.py first.",
            "index_name": index_name,
        }

    now = int(time.time())

    archives_scanned = 0
    archives_processed = 0
    files_seen = 0
    files_new = 0
    files_modified = 0
    files_unchanged = 0
    parse_errors = 0
    other_errors = 0

    errors = []

    with DBManager(db_path) as db:
        for archive_info in scan_archives(archives_root, sources):
            archives_scanned += 1
            archive_name = archive_info["archive_name"]

            if verbose:
                print(f"\nScanning archive: {archive_name}")

            any_change_in_archive = False

            for xml_info in stream_archive(archive_info["archive_path"]):
                files_seen += 1

                xml_path = xml_info["xml_path"]
                content_hash = hashlib.sha256(xml_info["xml_content"]).hexdigest()

                existing_hash = None if force else _get_existing_hash(db, xml_path)

                if existing_hash is None:
                    status = "new"
                elif existing_hash != content_hash:
                    status = "modified"
                else:
                    status = "unchanged"

                if status == "unchanged":
                    files_unchanged += 1
                    continue

                try:
                    parsed = parse_legifrance_xml(xml_info["xml_content"])
                    content = parsed.get("content") or ""
                    if not content.strip():
                        # Still store metadata but skip empty pages
                        # (keeps documents table consistent)
                        content = ""

                    # Upsert document
                    db.execute(
                        """INSERT OR REPLACE INTO documents
                           (path, file_type, language, page_count, size, modified_at, indexed_at,
                            content_hash, archive_name, xml_path, xml_id, nature, juridiction,
                            date_decision, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            xml_path,
                            "xml",
                            "french",
                            1,
                            int(xml_info.get("size") or len(xml_info["xml_content"])),
                            int(xml_info.get("mtime") or 0),
                            now,
                            content_hash,
                            archive_name,
                            xml_path,
                            parsed.get("xml_id") or xml_info.get("xml_id") or "",
                            parsed.get("nature") or "",
                            parsed.get("juridiction"),
                            parsed.get("date_decision"),
                            "{}",
                        ),
                    )

                    # Resolve doc_id
                    doc = db.query_one("SELECT id FROM documents WHERE path = ?", (xml_path,))
                    if doc and content.strip():
                        # Upsert page (page_number=1)
                        db.execute(
                            """INSERT OR REPLACE INTO pages
                               (doc_id, page_number, content, content_length, content_stem, was_ocr, ocr_confidence)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (
                                doc["id"],
                                1,
                                content,
                                len(content),
                                content,
                                0,
                                None,
                            ),
                        )

                    if status == "new":
                        files_new += 1
                    else:
                        files_modified += 1

                    any_change_in_archive = True

                    if verbose and (files_new + files_modified) % 500 == 0:
                        print(
                            f"  changes={files_new + files_modified} (new={files_new}, mod={files_modified})",
                            end="\r",
                        )

                except XMLParseError as e:
                    parse_errors += 1
                    if len(errors) < 20:
                        errors.append(f"XMLParseError: {xml_path}: {e}")
                except Exception as e:
                    other_errors += 1
                    if len(errors) < 20:
                        errors.append(f"Error: {xml_path}: {e}")

            if any_change_in_archive:
                archives_processed += 1

            db.commit()

    duration = time.time() - start_time

    return {
        "operation": "reindex",
        "status": "completed",
        "index_name": index_name,
        "archives_scanned": archives_scanned,
        "archives_processed": archives_processed,
        "files_seen": files_seen,
        "files_new": files_new,
        "files_modified": files_modified,
        "files_unchanged": files_unchanged,
        "parse_errors": parse_errors,
        "other_errors": other_errors,
        "duration_seconds": round(duration, 2),
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description="Reindex Legifrance archives incrementally")
    parser.add_argument("--index-name", required=True)
    parser.add_argument("--archives-root", required=True, help="Directory containing .tar.gz archives")
    parser.add_argument("--sources", help="Filter sources (comma-separated, ex: JORF,JADE)")
    parser.add_argument("--force", action="store_true", help="Force reindex (ignore hashes)")
    parser.add_argument("--verbose", action="store_true")

    args = parser.parse_args()

    archives_root = Path(args.archives_root).resolve()
    if not archives_root.exists():
        print(json.dumps({"status": "error", "error": f"archives_root not found: {archives_root}"}))
        sys.exit(2)

    sources = args.sources.split(",") if args.sources else None

    result = reindex_archives(
        index_name=args.index_name,
        archives_root=archives_root,
        sources=sources,
        verbose=args.verbose,
        force=args.force,
    )

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") != "error" else 1)


if __name__ == "__main__":
    main()
