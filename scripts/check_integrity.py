#!/usr/bin/env python3
"""Integrity checker for Lgifrance archives (freemium + incremental).

Goals
- Verify local archives against remote directory listings (missing files)
- Validate archive integrity without extracting (gzip test)
- Auto-fix mode:
  - delete corrupted archives
  - optionally relaunch downloader in background (nohup)

Designed for large datasets
- Streaming checks (gzip -t reads file sequentially)
- Lockfiles to prevent concurrent runs
- JSON report + log file

Paths (default)
- base_dir: /root/legifrance
  - archives/: archives by source
  - logs/: logs
  - config/: state + reports

Usage
- Report only:
    python check_integrity.py

- Auto-fix:
    python check_integrity.py --auto-fix

- Auto-fix + relaunch download:
    python check_integrity.py --auto-fix --relaunch-download

- Only one source:
    python check_integrity.py --source LEGI --auto-fix

Run in background:
    nohup python3 /root/legifrance/scripts/check_integrity.py --auto-fix --relaunch-download \
      > /root/legifrance/logs/integrity_nohup.log 2>&1 </dev/null &
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests

BASE_URL = "https://echanges.dila.gouv.fr/OPENDATA"

SOURCES_JURISPRUDENCE = ["CASS", "INCA", "CAPP", "JADE", "CONSTIT", "CNIL"]
SOURCES_CODES = ["LEGI", "JORF", "KALI"]
ALL_SOURCES = SOURCES_JURISPRUDENCE + SOURCES_CODES

LOCK_INTEGRITY = "/tmp/legifrance_integrity.lock"
LOCK_DOWNLOAD = "/tmp/legifrance_download.lock"


@dataclass(frozen=True)
class ArchiveRef:
    source: str
    name: str
    kind: str  # freemium|incremental
    date_key: str  # YYYYMMDD-HHMMSS


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _setup_logging(logs_dir: Path) -> logging.Logger:
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"integrity_{_now_stamp()}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("legifrance_integrity")
    logger.info(f"Log file: {log_file}")
    return logger


def _acquire_lock(lock_path: str, logger: logging.Logger) -> None:
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("utf-8"))
        os.close(fd)
    except FileExistsError:
        raise SystemExit(f"Lock exists: {lock_path} (another run in progress)")


def _release_lock(lock_path: str) -> None:
    try:
        os.unlink(lock_path)
    except FileNotFoundError:
        return


def _get_listing_html(source: str) -> str:
    url = f"{BASE_URL}/{source}/"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.text


def _parse_listing(source: str, html: str) -> List[ArchiveRef]:
    src_upper = source.upper()
    src_lower = source.lower()
    date_pat = r"(\d{8}-\d{6})"

    freemium_re = re.compile(
        rf"Freemium_{re.escape(src_lower)}_global_{date_pat}\.tar\.gz",
        re.IGNORECASE,
    )

    incr_re = re.compile(
        rf"{re.escape(src_upper)}_{date_pat}\.tar\.gz",
        re.IGNORECASE,
    )

    found: List[ArchiveRef] = []

    for m in freemium_re.finditer(html):
        found.append(ArchiveRef(src_upper, m.group(0), "freemium", m.group(1)))

    for m in incr_re.finditer(html):
        found.append(ArchiveRef(src_upper, m.group(0), "incremental", m.group(1)))

    uniq = {a.name: a for a in found}
    out = list(uniq.values())
    out.sort(key=lambda a: (0 if a.kind == "freemium" else 1, a.date_key))
    return out


def _local_archives(archives_dir: Path, source: str) -> Dict[str, Path]:
    base = archives_dir / source
    paths = list((base / "freemium").glob("*.tar.gz")) + list((base / "incremental").glob("*.tar.gz"))
    return {p.name: p for p in paths}


def _gzip_test(path: Path) -> bool:
    # gzip -t returns 0 if OK
    proc = subprocess.run(["gzip", "-t", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return proc.returncode == 0


def _delete_part_files(archives_dir: Path, logger: logging.Logger) -> int:
    count = 0
    for p in archives_dir.rglob("*.part"):
        try:
            p.unlink()
            count += 1
        except Exception as e:
            logger.warning(f"Could not delete .part: {p} ({e})")
    return count


def _write_report(config_dir: Path, report: Dict) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    out = config_dir / f"integrity_report_{_now_stamp()}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    return out


def _is_download_running() -> bool:
    return Path(LOCK_DOWNLOAD).exists()


def _launch_download_background(base_dir: Path, logger: logging.Logger) -> None:
    # Create download lock for the launcher (the download script itself does not create one)
    # We keep it simple: lock exists while a downloader process exists.
    if _is_download_running():
        logger.warning("Download lock already present, skipping relaunch.")
        return

    Path(LOCK_DOWNLOAD).write_text(str(os.getpid()), encoding="utf-8")
    log_path = base_dir / "logs" / f"download_repair_{_now_stamp()}.log"

    cmd = (
        f"cd {base_dir} && "
        f"nohup python3 scripts/download_archives.py --all > {log_path} 2>&1 </dev/null &"
    )

    subprocess.run(["sh", "-c", cmd], check=False)
    logger.info(f"Relaunched downloader in background. Log: {log_path}")
    logger.info(f"NOTE: Remove {LOCK_DOWNLOAD} when download completes (or we can auto-clean later).")


def main() -> int:
    ap = argparse.ArgumentParser(description="Check integrity of Legifrance archives")
    ap.add_argument("--base-dir", default="/root/legifrance", help="Base directory (default: /root/legifrance)")
    ap.add_argument("--source", help="Single source (e.g. LEGI)")
    ap.add_argument("--auto-fix", action="store_true", help="Delete corrupted archives and optionally relaunch download")
    ap.add_argument("--relaunch-download", action="store_true", help="Relaunch downloader in background if issues detected")

    args = ap.parse_args()

    base_dir = Path(args.base_dir)
    archives_dir = base_dir / "archives"
    logs_dir = base_dir / "logs"
    config_dir = base_dir / "config"

    logger = _setup_logging(logs_dir)

    _acquire_lock(LOCK_INTEGRITY, logger)
    try:
        sources = [args.source.upper()] if args.source else ALL_SOURCES

        deleted_parts = _delete_part_files(archives_dir, logger)
        if deleted_parts:
            logger.info(f"Deleted .part files: {deleted_parts}")

        report: Dict = {
            "base_dir": str(base_dir),
            "started_at": datetime.now().isoformat(),
            "sources": {},
            "totals": {"remote": 0, "local": 0, "missing": 0, "corrupted": 0, "ok": 0},
        }

        any_issue = False

        for source in sources:
            logger.info(f"--- {source} ---")
            html = _get_listing_html(source)
            remote_archives = _parse_listing(source, html)
            local_map = _local_archives(archives_dir, source)

            remote_names = {a.name for a in remote_archives}
            local_names = set(local_map.keys())

            missing = sorted(list(remote_names - local_names))

            corrupted: List[str] = []
            ok: List[str] = []

            # Test local files that are expected remotely
            for name in sorted(list(remote_names & local_names)):
                path = local_map[name]
                if _gzip_test(path):
                    ok.append(name)
                else:
                    corrupted.append(name)

            logger.info(
                f"remote={len(remote_names)} local={len(local_names)} missing={len(missing)} corrupted={len(corrupted)}"
            )

            if missing or corrupted:
                any_issue = True

            if args.auto_fix:
                for name in corrupted:
                    try:
                        local_map[name].unlink(missing_ok=True)
                        logger.warning(f"Deleted corrupted: {source}/{name}")
                    except Exception as e:
                        logger.error(f"Failed to delete corrupted {name}: {e}")

            report["sources"][source] = {
                "remote_count": len(remote_names),
                "local_count": len(local_names),
                "missing_count": len(missing),
                "corrupted_count": len(corrupted),
                "ok_count": len(ok),
                "missing": missing[:2000],
                "corrupted": corrupted[:2000],
            }

            report["totals"]["remote"] += len(remote_names)
            report["totals"]["local"] += len(local_names)
            report["totals"]["missing"] += len(missing)
            report["totals"]["corrupted"] += len(corrupted)
            report["totals"]["ok"] += len(ok)

        report["finished_at"] = datetime.now().isoformat()
        report_path = _write_report(config_dir, report)
        logger.info(f"Report written: {report_path}")

        if args.auto_fix and args.relaunch_download and any_issue:
            logger.warning("Issues detected; relaunching downloader in background...")
            _launch_download_background(base_dir, logger)

        if any_issue:
            return 2

        return 0

    finally:
        _release_lock(LOCK_INTEGRITY)


if __name__ == "__main__":
    raise SystemExit(main())
