"""Archive scanner for streaming tar.gz."""
import tarfile
from pathlib import Path
from typing import Generator, Dict, List, Optional
import re


def scan_archives(archives_root: Path, sources: Optional[List[str]] = None) -> Generator[Dict, None, None]:
    """Scan all archives in chronological order.
    
    Yields:
        {
            "archive_name": "JORF_20250714-010000.tar.gz",
            "archive_path": Path(...),
            "source": "JORF",
            "mtime": 1720915200
        }
    """
    if not archives_root.exists():
        return
    
    all_archives = []
    
    for archive_path in archives_root.rglob("*.tar.gz"):
        archive_name = archive_path.name
        source = _extract_source_name(archive_name)
        
        if sources and source not in sources:
            continue
        
        mtime = int(archive_path.stat().st_mtime)
        
        all_archives.append({
            "archive_name": archive_name,
            "archive_path": archive_path,
            "source": source,
            "mtime": mtime,
            "sort_key": _get_sort_key(archive_name)
        })
    
    all_archives.sort(key=lambda x: x["sort_key"])
    
    for info in all_archives:
        yield {k: v for k, v in info.items() if k != "sort_key"}


def stream_archive(archive_path: Path) -> Generator[Dict, None, None]:
    """Stream XML files from archive without extraction.
    
    Yields:
        {
            "archive_name": "JORF_20250714.tar.gz",
            "xml_path": "juri/JORF/TEXT/.../JORFTEXT000001.xml",
            "xml_id": "JORFTEXT000001",
            "xml_content": b"<?xml...",
            "size": 1234,
            "mtime": 1720915200
        }
    """
    archive_name = archive_path.name
    
    try:
        with tarfile.open(archive_path, 'r:gz') as tar:
            for member in tar:
                if not member.isfile() or not member.name.endswith('.xml'):
                    continue
                
                xml_id = Path(member.name).stem
                
                try:
                    f = tar.extractfile(member)
                    if f is None:
                        continue
                    
                    xml_content = f.read()
                    f.close()
                    
                    yield {
                        "archive_name": archive_name,
                        "xml_path": member.name,
                        "xml_id": xml_id,
                        "xml_content": xml_content,
                        "size": member.size,
                        "mtime": int(member.mtime)
                    }
                except Exception:
                    continue
    
    except tarfile.TarError:
        return


def _extract_source_name(archive_name: str) -> str:
    """Extract source from filename."""
    if archive_name.startswith("Freemium_"):
        parts = archive_name.split("_")
        if len(parts) >= 2:
            return parts[1].upper()
    else:
        parts = archive_name.split("_")
        if len(parts) >= 1:
            return parts[0].upper()
    return "UNKNOWN"


def _get_sort_key(archive_name: str) -> tuple:
    """Generate chronological sort key."""
    is_freemium = 0 if archive_name.startswith("Freemium_") else 1
    match = re.search(r'(\d{8}-\d{6})', archive_name)
    date_str = match.group(1) if match else "00000000-000000"
    return (is_freemium, date_str)
