#!/usr/bin/env python3
"""Download Légifrance archives (freemium + incremental).

Goals
- Download without extracting tar.gz (keeps inode usage low)
- Store under: docs/Legifrance/archives/<SOURCE>/{freemium|incremental}
- Maintain a state file: docs/Legifrance/config/download_state.json

Fix included (2026-01-07)
- Incremental filename matching is now case-insensitive, so CAPP works:
  - CAPP_YYYYMMDD-HHMMSS.tar.gz
  - Freemium_capp_global_YYYYMMDD-HHMMSS.tar.gz

Usage
- Full initial download:
    python download_archives.py --all

- Only freemium:
    python download_archives.py --freemium

- Only incremental:
    python download_archives.py --incremental

- Specific source:
    python download_archives.py --source CAPP --all
    python download_archives.py --source LEGI --freemium

- Download since date (incremental only):
    python download_archives.py --incremental --since 20250101

- Status:
    python download_archives.py --status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from tqdm import tqdm

# Paths
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
ARCHIVES_DIR = BASE_DIR / "archives"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
STATE_FILE = CONFIG_DIR / "download_state.json"

# Remote
BASE_URL = "https://echanges.dila.gouv.fr/OPENDATA"

# Sources
SOURCES_JURISPRUDENCE = ["CASS", "INCA", "CAPP", "JADE", "CONSTIT", "CNIL"]
SOURCES_CODES = ["LEGI", "JORF", "KALI"]
ALL_SOURCES = SOURCES_JURISPRUDENCE + SOURCES_CODES


class Colors:
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    OKCYAN = "\033[96m"
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"


@dataclass
class ArchiveRef:
    source: str
    name: str
    kind: str  # 'freemium' | 'incremental'
    date_key: str  # YYYYMMDD-HHMMSS


class ArchiveDownloader:
    """Download manager for Légifrance archives."""

    def __init__(self):
        self.setup_directories()
        self.setup_logging()
        self.state = self.load_state()

    # -------------------------
    # Setup
    # -------------------------

    def setup_directories(self):
        for source in ALL_SOURCES:
            (ARCHIVES_DIR / source / "freemium").mkdir(parents=True, exist_ok=True)
            (ARCHIVES_DIR / source / "incremental").mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def setup_logging(self):
        log_file = LOGS_DIR / f"download_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
        )
        self.logger = logging.getLogger(__name__)
        self.log_info(f"Logs enregistrés dans: {log_file}")

    # -------------------------
    # State
    # -------------------------

    def load_state(self) -> Dict:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "downloads": {},
            "last_download": {},
            "statistics": {"total_files": 0, "total_size_gb": 0},
            "last_run": None,
        }

    def save_state(self):
        self.state["last_run"] = datetime.now().isoformat()
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    # -------------------------
    # Logging helpers
    # -------------------------

    def log_success(self, msg: str):
        self.logger.info(f"{Colors.OKGREEN}✅ {msg}{Colors.ENDC}")

    def log_error(self, msg: str):
        self.logger.error(f"{Colors.FAIL}❌ {msg}{Colors.ENDC}")

    def log_info(self, msg: str):
        self.logger.info(f"{Colors.OKCYAN}ℹ️  {msg}{Colors.ENDC}")

    def log_warning(self, msg: str):
        self.logger.warning(f"{Colors.WARNING}⚠️  {msg}{Colors.ENDC}")

    # -------------------------
    # Listing parsing
    # -------------------------

    def get_directory_listing(self, source: str) -> str:
        url = f"{BASE_URL}/{source}/"
        self.log_info(f"Récupération du listing: {url}")
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.text

    def parse_listing(self, source: str, html: str) -> List[ArchiveRef]:
        """Parse directory listing HTML and return archives for this source.

        Robust to case: CAPP_... and capp_... are both accepted.
        """
        src_upper = source.upper()
        src_lower = source.lower()

        # Capture date key: YYYYMMDD-HHMMSS
        date_pat = r"(\d{8}-\d{6})"

        # Freemium pattern (server uses lower-case source in filename)
        freemium_re = re.compile(
            rf"Freemium_{re.escape(src_lower)}_global_{date_pat}\.tar\.gz",
            re.IGNORECASE,
        )

        # Incremental pattern (server uses UPPERCASE source)
        incr_re = re.compile(
            rf"{re.escape(src_upper)}_{date_pat}\.tar\.gz",
            re.IGNORECASE,
        )

        found: List[ArchiveRef] = []

        for m in freemium_re.finditer(html):
            name = m.group(0)
            date_key = m.group(1)
            found.append(ArchiveRef(source=src_upper, name=name, kind="freemium", date_key=date_key))

        for m in incr_re.finditer(html):
            name = m.group(0)
            date_key = m.group(1)
            found.append(ArchiveRef(source=src_upper, name=name, kind="incremental", date_key=date_key))

        # Deduplicate by name
        uniq = {a.name: a for a in found}
        found = list(uniq.values())

        # Sort: freemium first, then by date
        found.sort(key=lambda a: (0 if a.kind == "freemium" else 1, a.date_key))
        return found

    # -------------------------
    # Download
    # -------------------------

    def download_file(self, source: str, archive: ArchiveRef) -> Tuple[bool, int]:
        """Download a single archive. Returns (ok, size_bytes)."""
        target_dir = ARCHIVES_DIR / source / archive.kind
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / archive.name

        if out_path.exists() and out_path.stat().st_size > 0:
            return True, out_path.stat().st_size

        url = f"{BASE_URL}/{source}/{archive.name}"

        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", "0"))
                tmp_path = out_path.with_suffix(out_path.suffix + ".part")

                with open(tmp_path, "wb") as f, tqdm(
                    total=total if total > 0 else None,
                    unit="B",
                    unit_scale=True,
                    desc=archive.name,
                    leave=False,
                ) as bar:
                    size = 0
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        size += len(chunk)
                        if total > 0:
                            bar.update(len(chunk))

                os.replace(tmp_path, out_path)
                return True, size

        except Exception as e:
            self.log_error(f"Download failed for {archive.name}: {e}")
            try:
                if out_path.with_suffix(out_path.suffix + ".part").exists():
                    out_path.with_suffix(out_path.suffix + ".part").unlink()
            except Exception:
                pass
            return False, 0

    # -------------------------
    # High level operations
    # -------------------------

    def download_freemium(self, source: str) -> int:
        html = self.get_directory_listing(source)
        archives = [a for a in self.parse_listing(source, html) if a.kind == "freemium"]

        if not archives:
            self.log_warning(f"Aucune archive Freemium trouvée pour {source}")
            return 0

        self.log_success(f"Trouvé {len(archives)} archive(s) Freemium pour {source}")

        downloaded = 0
        for a in archives:
            ok, size = self.download_file(source, a)
            if ok:
                downloaded += 1
                self._record_download(source, a, size)
        return downloaded

    def download_incremental(self, source: str, since: Optional[str] = None) -> int:
        html = self.get_directory_listing(source)
        archives = [a for a in self.parse_listing(source, html) if a.kind == "incremental"]

        self.log_success(f"Trouvé {len(archives)} archives pour {source}")

        # Filter by since
        if since:
            # since is YYYYMMDD; archive date_key is YYYYMMDD-HHMMSS
            archives = [a for a in archives if a.date_key[:8] >= since]

        if not archives:
            self.log_info(f"Aucune archive incrémentale trouvée pour {source}")
            return 0

        downloaded = 0
        for a in archives:
            ok, size = self.download_file(source, a)
            if ok:
                downloaded += 1
                self._record_download(source, a, size)

        return downloaded

    def _record_download(self, source: str, a: ArchiveRef, size_bytes: int):
        self.state.setdefault("downloads", {}).setdefault(source, {})[a.name] = {
            "kind": a.kind,
            "date_key": a.date_key,
            "size": size_bytes,
            "downloaded_at": datetime.now().strftime("%Y%m%d"),
        }
        self.state.setdefault("last_download", {})[source] = datetime.now().strftime("%Y%m%d")

        self.state.setdefault("statistics", {}).setdefault("total_files", 0)
        self.state["statistics"]["total_files"] += 1

        self.state.setdefault("statistics", {}).setdefault("total_size_gb", 0.0)
        self.state["statistics"]["total_size_gb"] += size_bytes / (1024**3)

        self.save_state()

    # -------------------------
    # Status
    # -------------------------

    def print_status(self):
        print("\n" + "=" * 80)
        print("📊 Statut des téléchargements Légifrance")
        print("=" * 80 + "\n")

        header = f"{'Source':<12} {'Freemium':<9} {'Incr.':<7} {'Total':<7} {'Taille (GB)':<12} {'Dernière DL':<12}"
        print(header)
        print("-" * len(header))

        total_archives = 0
        total_size = 0.0

        for source in ALL_SOURCES:
            base = ARCHIVES_DIR / source
            freemium_count = len(list((base / "freemium").glob("*.tar.gz")))
            incr_count = len(list((base / "incremental").glob("*.tar.gz")))
            tot = freemium_count + incr_count

            size_gb = 0.0
            for p in list((base / "freemium").glob("*.tar.gz")) + list((base / "incremental").glob("*.tar.gz")):
                size_gb += p.stat().st_size / (1024**3)

            last_dl = self.state.get("last_download", {}).get(source, "Jamais")

            total_archives += tot
            total_size += size_gb

            print(f"{source:<12} {freemium_count:<9} {incr_count:<7} {tot:<7} {size_gb:<12.2f} {last_dl:<12}")

        print("-" * len(header))
        print(f"TOTAL{'':<8} {'':<9} {'':<7} {total_archives:<7} {total_size:<12.2f}")
        print(f"\nRépertoire des archives: {ARCHIVES_DIR}")
        print(f"Dernière exécution: {self.state.get('last_run', '-')}")


def main():
    parser = argparse.ArgumentParser(description="Download Légifrance archives")
    parser.add_argument("--source", help="Source (CASS, INCA, CAPP, JADE, CONSTIT, CNIL, LEGI, JORF, KALI)")

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--all", action="store_true", help="Download freemium + incremental")
    group.add_argument("--freemium", action="store_true", help="Download freemium only")
    group.add_argument("--incremental", action="store_true", help="Download incremental only")
    group.add_argument("--status", action="store_true", help="Show download status")

    parser.add_argument("--since", help="Since date (YYYYMMDD), incremental only")

    args = parser.parse_args()

    dl = ArchiveDownloader()

    if args.status:
        dl.print_status()
        return

    sources = [args.source.upper()] if args.source else ALL_SOURCES

    if args.all:
        dl.log_info("Téléchargement complet (Freemium + incrémental)")
        for s in sources:
            dl.log_info(f"--- {s} ---")
            dl.download_freemium(s)
            dl.download_incremental(s, since=args.since)
        dl.log_success("Téléchargement complet terminé")

    elif args.freemium:
        dl.log_info("Téléchargement initial Freemium")
        for s in sources:
            dl.download_freemium(s)
        dl.log_success("Téléchargement Freemium terminé")

    elif args.incremental:
        dl.log_info("Téléchargement des archives incrémentales")
        for s in sources:
            last = dl.state.get("last_download", {}).get(s)
            since = args.since
            if not since and last and re.match(r"^\d{8}$", last):
                since = last
            if not since:
                # default: from 30 days ago not implemented here; keep None
                pass
            dl.log_info(f"🔍 Recherche des archives incrémentales pour {s} (depuis {since or 'début'})...")
            dl.download_incremental(s, since=since)
        dl.log_success("✅ Téléchargement incrémental terminé")

    else:
        # default behavior = status
        dl.print_status()

    dl.print_status()


if __name__ == "__main__":
    main()
