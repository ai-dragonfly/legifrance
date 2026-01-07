#!/usr/bin/env python3
"""Index Legifrance archives (initial indexing).

Usage:
    python index_archives.py --index-name jorf_prod --archives-root ../archives
"""
import sys
import argparse
import json
import time
import hashlib
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from xml_parser import parse_legifrance_xml, XMLParseError
from archive_scanner import scan_archives, stream_archive
from db_manager import DBManager, create_legifrance_index


def index_archives(index_name: str, archives_root: Path, sources=None, verbose=False) -> dict:
    """Index all archives."""
    start_time = time.time()
    
    # DB path
    db_root = Path(__file__).parent.parent / "sqlite3"
    db_root.mkdir(exist_ok=True)
    db_path = db_root / f"index_{index_name}.db"
    
    # Check if index exists
    if db_path.exists():
        return {
            "operation": "index",
            "status": "error",
            "error": f"Index '{index_name}' already exists. Use reindex_archives.py for incremental update.",
            "index_name": index_name
        }
    
    # Create DB
    if verbose:
        print(f"Creating index: {index_name}")
    create_legifrance_index(db_path)
    
    # Metadata
    now = int(time.time())
    with DBManager(db_path) as db:
        db.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("mode", "fast"))
        db.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("created_at", str(now)))
        db.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("indexed_at", str(now)))
        db.execute("INSERT INTO index_metadata (key, value) VALUES (?, ?)", ("version", "2.0.0-xml"))
        db.commit()
    
    # Index
    archives_processed = 0
    files_processed = 0
    errors = []
    
    for archive_info in scan_archives(archives_root, sources):
        if verbose:
            print(f"\nProcessing: {archive_info['archive_name']}")
        
        archives_processed += 1
        archive_files = 0
        
        with DBManager(db_path) as db:
            for xml_info in stream_archive(archive_info['archive_path']):
                try:
                    # Parse XML
                    parsed = parse_legifrance_xml(xml_info['xml_content'])
                    
                    if not parsed['content'].strip():
                        continue
                    
                    # Hash
                    content_hash = hashlib.sha256(xml_info['xml_content']).hexdigest()
                    
                    # Insert document
                    db.execute(
                        """INSERT OR REPLACE INTO documents 
                           (path, file_type, language, page_count, size, modified_at, indexed_at,
                            content_hash, archive_name, xml_path, xml_id, nature, juridiction, 
                            date_decision, metadata_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            xml_info['xml_path'],  # path = xml_path
                            'xml',
                            'french',  # Default French
                            1,  # 1 XML = 1 page
                            xml_info['size'],
                            xml_info['mtime'],
                            now,
                            content_hash,
                            xml_info['archive_name'],
                            xml_info['xml_path'],
                            parsed['xml_id'],
                            parsed['nature'],
                            parsed['juridiction'],
                            parsed['date_decision'],
                            '{}'
                        )
                    )
                    
                    # Get doc_id
                    doc = db.query_one("SELECT id FROM documents WHERE path = ?", (xml_info['xml_path'],))
                    if not doc:
                        continue
                    
                    # Insert page
                    db.execute(
                        """INSERT OR REPLACE INTO pages 
                           (doc_id, page_number, content, content_length, content_stem, was_ocr, ocr_confidence)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            doc['id'],
                            1,  # Always page 1
                            parsed['content'],
                            len(parsed['content']),
                            parsed['content'],  # No stemming for now
                            0,
                            None
                        )
                    )
                    
                    archive_files += 1
                    files_processed += 1
                    
                    if verbose and files_processed % 100 == 0:
                        print(f"  Processed: {files_processed} files", end='\r')
                
                except XMLParseError as e:
                    errors.append(f"{xml_info['xml_path']}: {e}")
                except Exception as e:
                    errors.append(f"{xml_info['xml_path']}: {e}")
            
            db.commit()
        
        if verbose:
            print(f"  Archive: {archive_files} files indexed")
    
    duration = time.time() - start_time
    
    if verbose:
        print(f"\n✓ Indexing completed in {duration:.1f}s")
        print(f"  Archives: {archives_processed}")
        print(f"  Files: {files_processed}")
        if errors:
            print(f"  Errors: {len(errors)}")
    
    return {
        "operation": "index",
        "status": "completed",
        "index_name": index_name,
        "archives_processed": archives_processed,
        "files_processed": files_processed,
        "files_new": files_processed,
        "files_modified": 0,
        "files_unchanged": 0,
        "duration_seconds": round(duration, 2),
        "errors": errors[:10]  # First 10 errors
    }


def main():
    parser = argparse.ArgumentParser(description="Index Legifrance archives")
    parser.add_argument("--index-name", required=True, help="Index name")
    parser.add_argument("--archives-root", required=True, help="Archives directory")
    parser.add_argument("--sources", help="Filter sources (comma-separated, ex: JORF,JADE)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    
    args = parser.parse_args()
    
    archives_root = Path(args.archives_root).resolve()
    if not archives_root.exists():
        print(json.dumps({"error": f"Archives root not found: {archives_root}"}))
        sys.exit(2)
    
    sources = args.sources.split(",") if args.sources else None
    
    result = index_archives(args.index_name, archives_root, sources, args.verbose)
    
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "completed" else 1)


if __name__ == "__main__":
    main()
