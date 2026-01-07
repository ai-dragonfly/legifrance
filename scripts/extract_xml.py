#!/usr/bin/env python3
"""Extract XML from archive (for fs_requests).

Usage:
    python extract_xml.py --archive-path ../archives/JORF_20250714.tar.gz --xml-path juri/.../ID.xml
"""
import sys
import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from archive_scanner import stream_archive
from xml_parser import parse_legifrance_xml


def extract_xml(archive_path: Path, xml_path: str, output="xml") -> dict:
    """Extract single XML from archive."""
    if not archive_path.exists():
        return {"error": f"Archive not found: {archive_path}"}
    
    for xml_info in stream_archive(archive_path):
        if xml_info['xml_path'] == xml_path:
            if output == "xml":
                # Return raw XML
                print(xml_info['xml_content'].decode('utf-8'))
                return {}
            else:
                # Parse and return JSON
                parsed = parse_legifrance_xml(xml_info['xml_content'])
                return {
                    "xml_id": parsed['xml_id'],
                    "xml_path": xml_path,
                    "archive_name": archive_path.name,
                    "content": parsed['content'],
                    "metadata": {
                        "nature": parsed['nature'],
                        "juridiction": parsed['juridiction'],
                        "date_decision": parsed['date_decision']
                    }
                }
    
    return {"error": f"XML not found in archive: {xml_path}"}


def main():
    parser = argparse.ArgumentParser(description="Extract XML from archive")
    parser.add_argument("--archive-path", required=True, help="Archive file path")
    parser.add_argument("--xml-path", required=True, help="XML path in archive")
    parser.add_argument("--output", choices=["xml", "json"], default="xml")
    
    args = parser.parse_args()
    
    archive_path = Path(args.archive_path)
    result = extract_xml(archive_path, args.xml_path, args.output)
    
    if result and args.output == "json":
        print(json.dumps(result, indent=2))
        sys.exit(0 if "error" not in result else 1)


if __name__ == "__main__":
    main()
