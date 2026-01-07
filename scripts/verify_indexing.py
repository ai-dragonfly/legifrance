#!/usr/bin/env python3
"""Verify indexing completeness: count XMLs in archives vs DB.

Checks:
- Total XMLs in archives (tar.gz)
- Total docs in DB
- Missing documents
- Error rate
"""
import sys
import argparse
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from archive_scanner import scan_archives, stream_archive
from db_manager import DBManager


def count_xmls_in_archives(archives_root: Path) -> dict:
    """Count total XMLs in all archives."""
    total = 0
    by_archive = {}
    
    print(f"Scanning archives in {archives_root}...")
    
    for archive_info in scan_archives(archives_root):
        archive_name = archive_info['archive_name']
        count = 0
        
        for _ in stream_archive(archive_info['archive_path']):
            count += 1
        
        by_archive[archive_name] = count
        total += count
        print(f"  {archive_name}: {count:,} XMLs")
    
    return {
        "total": total,
        "by_archive": by_archive
    }


def count_docs_in_db(index_name: str) -> dict:
    """Count docs in DB."""
    db_root = Path(__file__).parent.parent / "sqlite3"
    db_path = db_root / f"index_{index_name}.db"
    
    if not db_path.exists():
        return {"error": f"Index {index_name} not found"}
    
    with DBManager(db_path) as db:
        # Total docs
        result = db.query_one("SELECT COUNT(*) as count FROM documents", ())
        total = result['count'] if result else 0
        
        # By archive
        by_archive = {}
        rows = db.query("SELECT archive_name, COUNT(*) as count FROM documents GROUP BY archive_name", ())
        for row in rows:
            by_archive[row['archive_name']] = row['count']
        
        # Metadata
        meta = {}
        meta_rows = db.query("SELECT key, value FROM index_metadata", ())
        for row in meta_rows:
            meta[row['key']] = row['value']
    
    return {
        "total": total,
        "by_archive": by_archive,
        "metadata": meta
    }


def verify_source(source: str, archives_root: Path) -> dict:
    """Verify single source."""
    print(f"\n{'='*60}")
    print(f"Verifying source: {source}")
    print(f"{'='*60}")
    
    # Count in archives
    print(f"\n1. Counting XMLs in archives/{source}/...")
    archive_counts = count_xmls_in_archives(archives_root / source)
    
    # Count in DB
    print(f"\n2. Counting docs in DB (index_{source.lower()}_prod)...")
    db_counts = count_docs_in_db(f"{source.lower()}_prod")
    
    if "error" in db_counts:
        print(f"  ⚠️  {db_counts['error']}")
        return {
            "source": source,
            "archive_xmls": archive_counts['total'],
            "db_docs": 0,
            "missing": archive_counts['total'],
            "coverage": 0.0
        }
    
    # Compare
    archive_total = archive_counts['total']
    db_total = db_counts['total']
    missing = archive_total - db_total
    coverage = (db_total / archive_total * 100) if archive_total > 0 else 0
    
    print(f"\n3. Comparison:")
    print(f"  Archives: {archive_total:,} XMLs")
    print(f"  Database: {db_total:,} docs")
    print(f"  Missing:  {missing:,} docs ({100-coverage:.1f}%)")
    print(f"  Coverage: {coverage:.1f}%")
    
    # Detail by archive
    if missing > 0:
        print(f"\n4. Missing by archive:")
        for archive_name, xml_count in archive_counts['by_archive'].items():
            db_count = db_counts['by_archive'].get(archive_name, 0)
            if xml_count != db_count:
                print(f"  ⚠️  {archive_name}: {xml_count:,} XMLs → {db_count:,} docs (missing: {xml_count - db_count:,})")
    
    return {
        "source": source,
        "archive_xmls": archive_total,
        "db_docs": db_total,
        "missing": missing,
        "coverage": round(coverage, 2),
        "by_archive": {
            name: {
                "xmls": archive_counts['by_archive'].get(name, 0),
                "docs": db_counts['by_archive'].get(name, 0)
            }
            for name in set(list(archive_counts['by_archive'].keys()) + list(db_counts['by_archive'].keys()))
        }
    }


def main():
    parser = argparse.ArgumentParser(description="Verify indexing completeness")
    parser.add_argument("--source", help="Source to verify (e.g., JORF, JADE, ALL)")
    parser.add_argument("--archives-root", default="../archives", help="Archives root")
    
    args = parser.parse_args()
    
    archives_root = Path(__file__).parent.parent / "archives"
    
    # Sources to verify
    if args.source and args.source.upper() != "ALL":
        sources = [args.source.upper()]
    else:
        sources = ["CNIL", "KALI", "CAPP", "CASS", "INCA", "LEGI", "JORF", "JADE", "CONSTIT"]
    
    # Verify each
    results = []
    for source in sources:
        result = verify_source(source, archives_root)
        results.append(result)
    
    # Summary
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    
    total_xmls = sum(r['archive_xmls'] for r in results)
    total_docs = sum(r['db_docs'] for r in results)
    total_missing = sum(r['missing'] for r in results)
    overall_coverage = (total_docs / total_xmls * 100) if total_xmls > 0 else 0
    
    print(f"\nTotal XMLs in archives: {total_xmls:,}")
    print(f"Total docs in DB:       {total_docs:,}")
    print(f"Total missing:          {total_missing:,}")
    print(f"Overall coverage:       {overall_coverage:.2f}%")
    
    print(f"\nBy source:")
    for r in results:
        status = "✅" if r['coverage'] >= 99.9 else "⚠️"
        print(f"  {status} {r['source']:8s}: {r['db_docs']:8,} / {r['archive_xmls']:8,} ({r['coverage']:5.1f}%)")
    
    # JSON output
    output = {
        "summary": {
            "total_xmls": total_xmls,
            "total_docs": total_docs,
            "total_missing": total_missing,
            "coverage": round(overall_coverage, 2)
        },
        "by_source": results
    }
    
    output_file = Path(__file__).parent.parent / "verification_report.json"
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)
    
    print(f"\n📄 Full report: {output_file}")


if __name__ == "__main__":
    main()
