#!/usr/bin/env python3
"""Update Légifrance archives (incremental sync).

This script updates local archives folders by downloading new incremental archives.

Fixes included (2026-01-07):
- Robust state initialization: ensure keys exist (last_update, last_download, downloads, statistics)
  => prevents KeyError: 'last_update'

Usage:
  cd docs/Legifrance

  # status
  python scripts/update_archives.py --status

  # update one source
  python scripts/update_archives.py --source CAPP

  # force update
  python scripts/update_archives.py --source CAPP --force

  # update by frequency buckets
  python scripts/update_archives.py --daily
  python scripts/update_archives.py --weekly
  python scripts/update_archives.py --monthly
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests
from tqdm import tqdm

# Paths
SCRIPT_DIR = Path(__file__).parent
BASE_DIR = SCRIPT_DIR.parent
ARCHIVES_DIR = BASE_DIR / "archives"
LOGS_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
STATE_FILE = CONFIG_DIR / "download_state.json"  # shared with download_archives.py

BASE_URL = "https://echanges.dila.gouv.fr/OPENDATA"

DAILY_SOURCES = ["JADE", "JORF"]
WEEKLY_SOURCES = ["CASS", "INCA", "CAPP", "CNIL", "LEGI", "KALI"]
MONTHLY_SOURCES = ["CONSTIT"]

ALL_SOURCES = DAILY_SOURCES + WEEKLY_SOURCES + MONTHLY_SOURCES


class Colors:
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    OKCYAN = "\033[96m"


@dataclass
class ArchiveRef:
    source: str
    name: str
    date_key: str  # YYYYMMDD-HHMMSS


class ArchiveUpdater:
    """Incremental archive updater."""

    def __init__(self):
        self.setup_directories()
        self.setup_logging()
        self.state = self.load_state()
        self.ensure_state_schema()

    def setup_directories(self):
        for source in ALL_SOURCES:
            (ARCHIVES_DIR / source / "freemium").mkdir(parents=True, exist_ok=True)
            (ARCHIVES_DIR / source / "incremental").mkdir(parents=True, exist_ok=True)
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    def setup_logging(self):
        log_file = LOGS_DIR / f"update_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
        )
        self.logger = logging.getLogger(__name__)
        self.log_info(f"Logs enregistrés dans: {log_file}")

    def log_info(self, msg: str):
        self.logger.info(f"{Colors.OKCYAN}ℹ️  {msg}{Colors.ENDC}")

    def log_success(self, msg: str):
        self.logger.info(f"{Colors.OKGREEN}✅ {msg}{Colors.ENDC}")

    def log_warning(self, msg: str):
        self.logger.warning(f"{Colors.WARNING}⚠️  {msg}{Colors.ENDC}")

    def log_error(self, msg: str):
        self.logger.error(f"{Colors.FAIL}❌ {msg}{Colors.ENDC}")

    def load_state(self) -> Dict:
        if STATE_FILE.exists():
            try:
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def ensure_state_schema(self):
        """Ensure required keys exist to avoid KeyError."""
        if not isinstance(self.state, dict):
            self.state = {}
        self.state.setdefault("downloads", {})
        self.state.setdefault("last_download", {})
        self.state.setdefault("last_update", {})
        self.state.setdefault("statistics", {"total_files": 0, "total_size_gb": 0})
        self.state.setdefault("last_run", None)

    def save_state(self):
        self.state["last_run"] = datetime.now().isoformat()
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(self.state, f, indent=2, ensure_ascii=False)

    # -------------------------
    # Listing
    # -------------------------

    def get_listing(self, source: str) -> str:
        url = f"{BASE_URL}/{source}/"
        self.log_info(f"Récupération du listing: {url}")
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return resp.text

    def parse_incremental(self, source: str, html: str) -> List[ArchiveRef]:
        src_upper = source.upper()
        date_pat = r"(\d{8}-\d{6})"
        incr_re = re.compile(rf"{re.escape(src_upper)}_{date_pat}\.tar\.gz", re.IGNORECASE)

        found: List[ArchiveRef] = []
        for m in incr_re.finditer(html):
            name = m.group(0)
            date_key = m.group(1)
            found.append(ArchiveRef(source=src_upper, name=name, date_key=date_key))

        # Deduplicate
        uniq = {a.name: a for a in found}
        found = list(uniq.values())
        found.sort(key=lambda a: a.date_key)
        return found

    # -------------------------
    # Download
    # -------------------------

    def download_archive(self, source: str, archive: ArchiveRef) -> bool:
        target_dir = ARCHIVES_DIR / source / "incremental"
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / archive.name
        if out_path.exists() and out_path.stat().st_size > 0:
            return True

        url = f"{BASE_URL}/{source}/{archive.name}"
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length", "0"))
                tmp = out_path.with_suffix(out_path.suffix + ".part")
                with open(tmp, "wb") as f, tqdm(
                    total=total if total > 0 else None,
                    unit="B",
                    unit_scale=True,
                    desc=archive.name,
                    leave=False,
                ) as bar:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        f.write(chunk)
                        if total > 0:
                            bar.update(len(chunk))
                tmp.replace(out_path)
            return True
        except Exception as e:
            self.log_error(f"Download failed: {archive.name}: {e}")
            return False

    # -------------------------
    # Update logic
    # -------------------------

    def needs_update(self, source: str, force: bool) -> bool:
        if force:
            self.log_info(f"{source}: Mise à jour forcée")
            return True

        last = self.state.get("last_update", {}).get(source)
        if not last:
            self.log_info(f"{source}: Jamais synchronisé")
            return True

        # frequency policy
        now = datetime.now()
        last_dt = None
        try:
            last_dt = datetime.fromisoformat(last)
        except Exception:
            return True

        if source in DAILY_SOURCES:
            return (now - last_dt) > timedelta(days=1)
        if source in WEEKLY_SOURCES:
            return (now - last_dt) > timedelta(days=7)
        if source in MONTHLY_SOURCES:
            return (now - last_dt) > timedelta(days=30)

        return True

    def update_source(self, source: str, force: bool = False):
        source = source.upper()
        self.log_info(f"🔄 Vérification des mises à jour pour {source}...")

        if not self.needs_update(source, force):
            self.log_success(f"{source}: Pas de mise à jour nécessaire")
            return

        # Find local last archive date (YYYYMMDD)
        local_dir = ARCHIVES_DIR / source / "incremental"
        local_dates = []
        for p in local_dir.glob(f"{source}_*.tar.gz"):
            m = re.search(r"(\d{8})-\d{6}", p.name)
            if m:
                local_dates.append(m.group(1))
        last_local = max(local_dates) if local_dates else None
        self.log_info(f"{source}: Dernière archive locale: {last_local or 'Aucune'}")

        # Listing
        html = self.get_listing(source)
        remotes = self.parse_incremental(source, html)
        self.log_success(f"Trouvé {len(remotes)} archives pour {source}")

        # Filter: newer than last_local
        if last_local:
            remotes = [a for a in remotes if a.date_key[:8] > last_local]

        if not remotes:
            self.log_info(f"{source}: Aucune nouvelle archive disponible")
            # record update time anyway
            self.state["last_update"][source] = datetime.now().isoformat()
            self.save_state()
            return

        # Download
        downloaded = 0
        for a in remotes:
            ok = self.download_archive(source, a)
            if ok:
                downloaded += 1

        self.log_success(f"{source}: Téléchargé {downloaded} nouvelles archives")
        self.state["last_update"][source] = datetime.now().isoformat()
        self.save_state()

    def get_statistics(self) -> List[Dict]:
        stats = []
        for source in ALL_SOURCES:
            base = ARCHIVES_DIR / source
            freemium_count = len(list((base / "freemium").glob("*.tar.gz")))
            incr_count = len(list((base / "incremental").glob("*.tar.gz")))
            size_gb = 0.0
            for p in list((base / "freemium").glob("*.tar.gz")) + list((base / "incremental").glob("*.tar.gz")):
                size_gb += p.stat().st_size / (1024**3)

            stats.append(
                {
                    "source": source,
                    "freemium": freemium_count,
                    "incremental": incr_count,
                    "total": freemium_count + incr_count,
                    "size_gb": round(size_gb, 2),
                    "last_update": self.state.get("last_update", {}).get(source, "Jamais"),
                }
            )
        return stats

    def print_status(self):
        print("\n" + "=" * 95)
        print("📊 Statut des archives Légifrance")
        print("=" * 95 + "\n")

        header = f"{'Source':<10} {'Freemium':<9} {'Incr.':<7} {'Total':<7} {'Taille (GB)':<12} {'Dernière MAJ':<24}"
        print(header)
        print("-" * len(header))

        total_archives = 0
        total_size = 0.0

        for row in self.get_statistics():
            total_archives += row["total"]
            total_size += row["size_gb"]
            print(
                f"{row['source']:<10} {row['freemium']:<9} {row['incremental']:<7} {row['total']:<7} {row['size_gb']:<12.2f} {row['last_update']:<24}"
            )

        print("-" * len(header))
        print(f"TOTAL{'':<6} {'':<9} {'':<7} {total_archives:<7} {total_size:<12.2f}")
        print(f"\nRépertoire des archives: {ARCHIVES_DIR}")
        print(f"Dernière exécution: {self.state.get('last_run', '-')}")


def main():
    parser = argparse.ArgumentParser(description="Update Légifrance archives")
    parser.add_argument("--source", help="Single source (e.g., CAPP)")
    parser.add_argument("--force", action="store_true", help="Force update")

    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument("--status", action="store_true", help="Show status")
    group.add_argument("--daily", action="store_true", help="Update daily sources")
    group.add_argument("--weekly", action="store_true", help="Update weekly sources")
    group.add_argument("--monthly", action="store_true", help="Update monthly sources")

    args = parser.parse_args()

    updater = ArchiveUpdater()

    if args.status:
        updater.print_status()
        return

    if args.source:
        updater.update_source(args.source, force=args.force)
        updater.print_status()
        return

    if args.daily:
        for s in DAILY_SOURCES:
            updater.update_source(s, force=args.force)
        updater.print_status()
        return

    if args.weekly:
        for s in WEEKLY_SOURCES:
            updater.update_source(s, force=args.force)
        updater.print_status()
        return

    if args.monthly:
        for s in MONTHLY_SOURCES:
            updater.update_source(s, force=args.force)
        updater.print_status()
        return

    # Default: status
    updater.print_status()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\n❌ Erreur fatale:", str(e))
        raise
