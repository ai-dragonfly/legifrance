#!/usr/bin/env python3
"""Search Legifrance index.

Usage:
    python search_index.py --index-name jorf_prod --query "contrat travail" --limit 10
"""
import sys
import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from db_manager import DBManager


def search_index(index_name: str, query: str, limit=10, min_score=0.1, output_format="json") -> dict:
    """Search index using FTS5."""
    db_root = Path(__file__).parent.parent / "sqlite3"
    db_path = db_root / f"index_{index_name}.db"
    
    if not db_path.exists():
        return {
            "operation": "search",
            "status": "error",
            "error": f"Index '{index_name}' not found"
        }
    
    with DBManager(db_path) as db:
        # FTS5 search
        results_raw = db.query(
            """
            SELECT 
                d.id,
                d.xml_path,
                d.xml_id,
                d.archive_name,
                d.nature,
                d.juridiction,
                d.date_decision,
                p.content,
                f.rank
            FROM content_fts f
            JOIN pages p ON f.rowid = p.id
            JOIN documents d ON p.doc_id = d.id
            WHERE content_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit)
        )
    
    # Build results
    results = []
    for row in results_raw:
        # Simple score (FTS5 rank is negative, closer to 0 = better)
        score = min(1.0, abs(1.0 / (row['rank'] - 0.1)))
        
        if score < min_score:
            continue
        
        # Snippet (first 200 chars with query context)
        content = row['content']
        query_lower = query.lower()
        idx = content.lower().find(query_lower)
        if idx >= 0:
            start = max(0, idx - 50)
            end = min(len(content), idx + 150)
            snippet = content[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(content):
                snippet = snippet + "..."
        else:
            snippet = content[:200] + "..."
        
        results.append({
            "xml_path": row['xml_path'],
            "xml_id": row['xml_id'],
            "archive_name": row['archive_name'],
            "score": round(score, 2),
            "snippet": snippet,
            "nature": row['nature'],
            "juridiction": row['juridiction'],
            "date_decision": row['date_decision']
        })
    
    # Output format
    if output_format == "fs-requests":
        return {
            "fs_requests": [
                {
                    "action": "load_xml",
                    "xml_path": r['xml_path'],
                    "archive_name": r['archive_name'],
                    "xml_id": r['xml_id']
                }
                for r in results[:3]  # Top 3
            ]
        }
    
    return {
        "operation": "search",
        "query": query,
        "total_count": len(results),
        "returned_count": len(results),
        "results": results
    }


def main():
    parser = argparse.ArgumentParser(description="Search Legifrance index")
    parser.add_argument("--index-name", required=True, help="Index name")
    parser.add_argument("--query", required=True, help="Search query")
    parser.add_argument("--limit", type=int, default=10, help="Max results")
    parser.add_argument("--min-score", type=float, default=0.1, help="Min score")
    parser.add_argument("--output-format", choices=["json", "fs-requests"], default="json")
    
    args = parser.parse_args()
    
    result = search_index(args.index_name, args.query, args.limit, args.min_score, args.output_format)
    
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") != "error" else 1)


if __name__ == "__main__":
    main()
