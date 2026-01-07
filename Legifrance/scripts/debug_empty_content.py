#!/usr/bin/env python3
"""Debug files skipped because extract_content_blocks() returns empty.

Goal:
- Sample XMLs where <CONTENU> yields empty
- Measure how much text exists via itertext() fallback
- Classify likely cases:
  A) truly empty / parse error
  B) structural/metadata (low text)
  C) real text elsewhere (large itertext) => data loss today

Usage:
  cd docs/Legifrance
  python scripts/debug_empty_content.py --source CNIL --max 50
  python scripts/debug_empty_content.py --source LEGI --max 50 --only-freemium
"""
import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from archive_scanner import scan_archives, stream_archive
from xml_parser import XMLParseError
import xml.etree.ElementTree as ET


def extract_contenu_only(xml_bytes: bytes) -> str:
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    blocks = root.findall(".//CONTENU")
    texts = [b.text.strip() for b in blocks if b.text and b.text.strip()]
    return "\n\n".join(texts)


def extract_itertext(xml_bytes: bytes) -> str:
    root = ET.fromstring(xml_bytes.decode("utf-8"))
    parts = [t.strip() for t in root.itertext() if t and t.strip()]
    return " ".join(parts)


def classify(itertext_len: int, threshold: int) -> str:
    if itertext_len == 0:
        return "A_EMPTY"
    if itertext_len < threshold:
        return "B_STRUCT"
    return "C_TEXT_ELSEWHERE"


def main():
    parser = argparse.ArgumentParser(description="Debug empty <CONTENU> extraction")
    parser.add_argument("--source", required=True, help="Source folder under archives/ (e.g., CNIL, LEGI, JORF, JADE, CASS)")
    parser.add_argument("--max", type=int, default=50, help="Max samples to report")
    parser.add_argument("--threshold", type=int, default=500, help="itertext length threshold for C_TEXT_ELSEWHERE")
    parser.add_argument("--only-freemium", action="store_true", help="Only scan freemium subfolder")
    parser.add_argument("--only-incremental", action="store_true", help="Only scan incremental subfolder")

    args = parser.parse_args()

    base = Path(__file__).parent.parent
    archives_root = base / "archives" / args.source.upper()

    if args.only_freemium and args.only_incremental:
        print("ERROR: choose only one of --only-freemium / --only-incremental")
        sys.exit(2)

    if args.only_freemium:
        scan_root = archives_root / "freemium"
    elif args.only_incremental:
        scan_root = archives_root / "incremental"
    else:
        scan_root = archives_root

    if not scan_root.exists():
        print(f"ERROR: not found: {scan_root}")
        sys.exit(2)

    total_xml = 0
    total_parse_errors = 0
    total_skipped_by_contenu = 0

    buckets = {"A_EMPTY": 0, "B_STRUCT": 0, "C_TEXT_ELSEWHERE": 0}

    printed = 0

    # We scan archives in this source folder
    for archive_info in scan_archives(scan_root):
        for xml_info in stream_archive(archive_info["archive_path"]):
            total_xml += 1
            xml_path = xml_info["xml_path"]
            xml_bytes = xml_info["xml_content"]

            try:
                contenu = extract_contenu_only(xml_bytes)
            except Exception:
                total_parse_errors += 1
                continue

            if contenu.strip():
                continue  # not our target

            total_skipped_by_contenu += 1

            # Now measure itertext
            try:
                it = extract_itertext(xml_bytes)
                it_len = len(it)
            except Exception:
                total_parse_errors += 1
                continue

            bucket = classify(it_len, args.threshold)
            buckets[bucket] += 1

            if printed < args.max:
                print("-")
                print(f"archive: {xml_info['archive_name']}")
                print(f"xml_path: {xml_path}")
                print(f"size: {xml_info['size']} bytes")
                print(f"contenu_len: 0")
                print(f"itertext_len: {it_len}")
                print(f"bucket: {bucket}")
                print(f"itertext_preview: {it[:300].replace('\n',' ')}")
                printed += 1

    # Summary
    print("\n=== SUMMARY ===")
    print(f"source: {args.source.upper()}")
    print(f"scan_root: {scan_root}")
    print(f"total_xml_seen: {total_xml:,}")
    print(f"parse_errors: {total_parse_errors:,}")
    print(f"contenu_empty_count: {total_skipped_by_contenu:,}")
    print("buckets:")
    for k, v in buckets.items():
        pct = (v / total_skipped_by_contenu * 100) if total_skipped_by_contenu else 0
        print(f"  - {k}: {v:,} ({pct:.1f}%)")


if __name__ == "__main__":
    main()
