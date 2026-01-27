#!/usr/bin/env python3
"""Orchestrateur quotidien Légifrance (ingestion PostgreSQL).

But
- Exécute la chaîne quotidienne à 04:00 Europe/Paris (via systemd timer)
- Téléchargement incrémental
- Integrity check auto-fix
- Ingestion PostgreSQL (LEGI + JORF) via streaming tar.gz
- Calcul statistiques codes (table code_stats)
- Régénération caches obsolètes (table code_trees) ✨ NOUVEAU
- Sanity checks (disk/inodes + state updated)

Contrainte
- Big logs, lockfile, no interactive

Logs
- /root/legifrance/logs/pipeline_YYYYMMDD-HHMMSS.log

Lock
- /tmp/legifrance_pipeline.lock

Exit codes
- 0: OK
- 2: verrou déjà présent
- 3: échec à l'étape download
- 4: échec à l'étape integrity
- 5: échec à l'étape ingest
- 6: échec à l'étape compute_stats (non-fatal)
- 7: échec sanity (inodes critique / state absent)
- 8: échec cache regeneration (non-fatal)
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOCK_PATH = "/tmp/legifrance_pipeline.lock"

BASE_DIR = Path("/root/legifrance")
LOGS_DIR = BASE_DIR / "logs"
CONFIG_DIR = BASE_DIR / "config"
SCRIPT_DIR = BASE_DIR / "scripts"
PYTHON = "/usr/bin/python3"


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _setup_logging() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"pipeline_{_now_stamp()}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("legifrance_pipeline")
    logger.info(f"Log file: {log_file}")
    return logger


def _acquire_lock() -> None:
    fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode("utf-8"))
    os.close(fd)


def _release_lock() -> None:
    try:
        os.unlink(LOCK_PATH)
    except FileNotFoundError:
        return


def _run(logger: logging.Logger, cmd: list[str], step: str, timeout: int = 3600) -> int:
    logger.info(f"== STEP {step} ==")
    logger.info("CMD: %s", " ".join(cmd))
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        out = proc.stdout.decode("utf-8", errors="replace")
        if out.strip():
            logger.info(out.rstrip())
        return proc.returncode
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout in step {step} after {timeout}s")
        return 124


def _sanity(logger: logging.Logger) -> bool:
    # check disk and inodes
    logger.info("== STEP sanity ==")
    subprocess.run(["df", "-h", "/mnt/data"], check=False)
    p = subprocess.run(["df", "-i", "/mnt/data"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = p.stdout.decode("utf-8", errors="replace")
    logger.info(out.rstrip())

    # crude inode threshold: fail if 95%+
    try:
        lines = out.strip().splitlines()
        if len(lines) >= 2:
            cols = lines[1].split()
            iuse = cols[4]  # e.g. '63%'
            pct = int(iuse.replace("%", ""))
            if pct >= 95:
                logger.error(f"INODES too high: {pct}%")
                return False
    except Exception:
        pass

    # check state file exists
    state = CONFIG_DIR / "ingest_state.json"
    if not state.exists():
        logger.error(f"Missing state file: {state}")
        return False

    return True


def main() -> int:
    logger = _setup_logging()

    try:
        _acquire_lock()
    except FileExistsError:
        logger.error(f"Lock exists: {LOCK_PATH}")
        return 2

    report = {
        "started_at": datetime.now().isoformat(),
        "steps": {},
    }

    try:
        # 1) download incremental
        rc = _run(
            logger,
            [PYTHON, str(SCRIPT_DIR / "download_archives.py"), "--incremental"],
            step="download_incremental",
            timeout=6 * 3600,
        )
        report["steps"]["download_incremental"] = rc
        if rc != 0:
            return 3

        # 2) integrity auto-fix (may relaunch download if issues)
        rc = _run(
            logger,
            [PYTHON, str(SCRIPT_DIR / "check_integrity.py"), "--auto-fix", "--relaunch-download"],
            step="integrity",
            timeout=6 * 3600,
        )
        report["steps"]["integrity"] = rc
        if rc not in (0, 2):
            # 2 = issues detected (non fatal if fixed/relaunched)
            return 4

        # 3) ingest PostgreSQL daily (LEGI + JORF)
        rc = _run(
            logger,
            [PYTHON, str(SCRIPT_DIR / "ingest_legifrance_pg.py"), "--daily", "--sources", "LEGI"],
            step="ingest_pg_daily",
            timeout=12 * 3600,
        )
        report["steps"]["ingest_pg_daily"] = rc
        if rc != 0:
            return 5

        # 4) compute code stats (pré-calcul pour accélération CLI)
        rc = _run(
            logger,
            [PYTHON, str(SCRIPT_DIR / "compute_code_stats_v2.py")],
            step="compute_code_stats",
            timeout=6 * 3600,
        )
        report["steps"]["compute_code_stats"] = rc
        if rc != 0:
            logger.warning(f"compute_code_stats failed with rc={rc}, continuing...")
            # Non-fatal: on continue même si le calcul échoue
            # Le CLI fonctionnera avec des données obsolètes

        # 5) ✨ NOUVEAU : Regenerate stale caches (codes modifiés dernières 24h)
        logger.info("=" * 80)
        logger.info("STEP 5: Regenerate stale caches (code_trees)")
        logger.info("=" * 80)
        
        try:
            rc = _run(
                logger,
                [PYTHON, str(SCRIPT_DIR / "regenerate_stale_caches.py"), "--verbose"],
                step="regenerate_caches",
                timeout=30 * 60,  # 30 min max
            )
            report["steps"]["regenerate_caches"] = rc
            
            if rc == 0:
                logger.info("✅ Cache regeneration completed successfully")
            else:
                logger.warning(f"⚠️  Cache regeneration returned {rc} (non-fatal, continuing...)")
                # Non-fatal : on continue même si régénération échoue
                # Le CLI utilisera les caches existants
        except Exception as e:
            logger.warning(f"⚠️  Cache regeneration failed: {e} (non-fatal, continuing...)")
            report["steps"]["regenerate_caches"] = "error"

        # 6) sanity
        ok = _sanity(logger)
        report["sanity_ok"] = ok
        if not ok:
            return 7

        return 0

    finally:
        report["finished_at"] = datetime.now().isoformat()
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        rep_file = CONFIG_DIR / f"pipeline_report_{_now_stamp()}.json"
        rep_file.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info(f"Report written: {rep_file}")
        _release_lock()


if __name__ == "__main__":
    raise SystemExit(main())
