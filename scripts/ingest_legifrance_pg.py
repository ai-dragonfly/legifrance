#!/usr/bin/env python3
"""Ingestion Légifrance -> PostgreSQL (streaming, sans extraction disque).

Périmètre MVP
- Sources : LEGI + JORF
- DB : PostgreSQL local (peer)
- Stockage : content_xml + content_text + meta

Principes
- Lit les `.tar.gz` via tarfile en mode streaming (r|*)
- Parse XML avec lxml (rapide)
- Upsert dans table `documents`
- Applique les suppressions via `liste_suppression_*.dat`

State
- /root/legifrance/config/ingest_state.json
  - last_incremental par source

Lock
- /tmp/legifrance_ingest.lock

Logs
- /root/legifrance/logs/ingest_pg_YYYYMMDD-HHMMSS.log

Usage
- Init (freemium + tous incrémentaux existants):
    python ingest_legifrance_pg.py --init --sources LEGI,JORF

- Daily (uniquement nouveaux incrémentaux):
    python ingest_legifrance_pg.py --daily --sources LEGI,JORF

Notes
- Ce script suppose que les archives sont déjà téléchargées dans:
  /root/legifrance/archives/<SOURCE>/{freemium|incremental}
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import os
import re
import sys
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

import psycopg
from lxml import etree

BASE_DIR = Path("/root/legifrance")
ARCHIVES_DIR = BASE_DIR / "archives"
CONFIG_DIR = BASE_DIR / "config"
LOGS_DIR = BASE_DIR / "logs"

STATE_PATH = CONFIG_DIR / "ingest_state.json"
LOCK_PATH = "/tmp/legifrance_ingest.lock"

DEFAULT_DB = {
    "dbname": "legifrance",
    "user": "legifrance_app",
    # peer auth -> no password needed
    "host": "/var/run/postgresql",  # unix socket
}


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _setup_logging() -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOGS_DIR / f"ingest_pg_{_now_stamp()}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_file), logging.StreamHandler(sys.stdout)],
    )
    logger = logging.getLogger("legifrance_ingest_pg")
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


def _load_state() -> Dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: Dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def _iter_archives(source: str, mode: str) -> List[Path]:
    """Return ordered list of archives to process.

    mode:
      - init: freemium then all incrementals
      - daily: only incrementals after last state
    """
    source = source.upper()
    base = ARCHIVES_DIR / source

    freemium = sorted((base / "freemium").glob("*.tar.gz"), key=lambda p: p.name)
    incr = sorted((base / "incremental").glob("*.tar.gz"), key=_date_key)

    if mode == "init":
        return freemium + incr

    state = _load_state()
    last = state.get("sources", {}).get(source, {}).get("last_incremental")

    if not last:
        # if no state, safer to do nothing in daily (require init)
        return []

    started = False
    out: List[Path] = []
    for p in incr:
        if not started:
            if p.name == last:
                started = True
            continue
        out.append(p)

    return out


def _date_key(path: Path) -> str:
    m = re.search(r"(\d{8}-\d{6})", path.name)
    return m.group(1) if m else path.name


def _guess_doctype(path_in_tar: str) -> str:
    p = path_in_tar.lower()
    if p.endswith(".xml"):
        # heuristics
        if "/article" in p or "article" in p:
            return "article"
        if "/texte" in p or "texte" in p:
            return "texte"
        if "/section_ta" in p or "section_ta" in p:
            return "section"
        return "xml"
    if p.endswith(".dat"):
        if "liste_suppression" in p:
            return "suppression_list"
        return "dat"
    return "blob"


def _extract_text_and_meta_from_xml(xml_bytes: bytes, path_in_tar: str) -> Tuple[str, Dict]:
    """Parse XML and return (text, meta).

    Enhanced parsing: extract structural metadata based on XML type.
    """
    try:
        root = etree.fromstring(xml_bytes)
        text = " ".join([t.strip() for t in root.itertext() if t and t.strip()])
        
        meta = {
            "root_tag": str(root.tag),
        }
        
        # Extract common attributes
        for k in ("id", "cid", "name"):
            if k in root.attrib:
                meta[k] = root.attrib.get(k)
        
        # Type-specific parsing
        root_tag = str(root.tag)
        
        if root_tag == "TEXTE_VERSION":
            # Code/TNC metadata - CORRECTED: navigate to proper path
            # Structure: <TEXTE_VERSION><META><META_COMMUN> and <META><META_SPEC><META_TEXTE_VERSION>
            
            # ID et NATURE dans META_COMMUN
            meta_commun = root.find("META/META_COMMUN")
            if meta_commun is not None:
                id_elem = meta_commun.find("ID")
                nature_elem = meta_commun.find("NATURE")
                if id_elem is not None and id_elem.text:
                    meta["id"] = id_elem.text
                if nature_elem is not None and nature_elem.text:
                    meta["nature"] = nature_elem.text
            
            # TITRE, ETAT, dates dans META_SPEC/META_TEXTE_VERSION
            meta_texte_version = root.find("META/META_SPEC/META_TEXTE_VERSION")
            if meta_texte_version is not None:
                titre_elem = meta_texte_version.find("TITRE")
                titrefull_elem = meta_texte_version.find("TITREFULL")
                etat_elem = meta_texte_version.find("ETAT")
                date_debut_elem = meta_texte_version.find("DATE_DEBUT")
                date_fin_elem = meta_texte_version.find("DATE_FIN")
                
                if titrefull_elem is not None and titrefull_elem.text:
                    meta["titre"] = titrefull_elem.text
                elif titre_elem is not None and titre_elem.text:
                    meta["titre"] = titre_elem.text
                
                if etat_elem is not None and etat_elem.text:
                    meta["etat"] = etat_elem.text
                
                if date_debut_elem is not None and date_debut_elem.text:
                    meta["date_debut"] = date_debut_elem.text
                
                if date_fin_elem is not None and date_fin_elem.text:
                    meta["date_fin"] = date_fin_elem.text
        
        elif root_tag == "SECTION_TA":
            # Section hierarchy
            meta["id"] = root.find("ID").text if root.find("ID") is not None else None
            meta["titre"] = root.find("TITRE_TA").text if root.find("TITRE_TA") is not None else None
            
            # Extract parent from CONTEXTE/TEXTE (the XML doesn't have a direct PARENT tag)
            parent = None
            contexte_texte = root.find("CONTEXTE/TEXTE")
            if contexte_texte is not None:
                # Try id_txt attribute first
                parent = contexte_texte.get("id_txt")
                # If not found, try TITRE_TXT/@id_txt
                if not parent:
                    titre_txt = contexte_texte.find("TITRE_TXT")
                    if titre_txt is not None:
                        parent = titre_txt.get("id_txt")
            
            # Fallback: extract from path (look for LEGITEXT or JORFTEXT before /section_ta/)
            if not parent:
                match = re.search(r'/((?:LEGI|JORF)TEXT\d{12})/section_ta/', path_in_tar)
                if match:
                    parent = match.group(1)
            
            meta["parent"] = parent
            
            # Count children
            liens_section = root.findall(".//LIEN_SECTION_TA")
            liens_art = root.findall(".//LIEN_ART")
            meta["nb_sections"] = len(liens_section)
            meta["nb_articles"] = len(liens_art)
            # ========================================
            # v3.0 : PHASE 2 + 3 - STRUCTURE_TA
            # ========================================
            structure_ta = root.find("STRUCTURE_TA")
            if structure_ta is not None:
                # PHASE 2: Sous-sections
                liens_section_ta = structure_ta.findall("LIEN_SECTION_TA")
                sous_sections = []
                for lien in liens_section_ta:
                    sous_section_id = lien.get("id")
                    if sous_section_id:
                        sous_sections.append({
                            "id": sous_section_id,
                            "debut": lien.get("debut"),
                            "fin": lien.get("fin"),
                            "etat": lien.get("etat")
                        })
                
                if sous_sections:
                    meta["sous_sections"] = sous_sections
                
                # PHASE 3: Articles
                liens_art_ta = structure_ta.findall("LIEN_ART")
                articles = []
                for lien in liens_art_ta:
                    article_id = lien.get("id")
                    if article_id:
                        articles.append({
                            "id": article_id,
                            "num": lien.get("num"),
                            "debut": lien.get("debut"),
                            "fin": lien.get("fin"),
                            "etat": lien.get("etat"),
                            "origine": lien.get("origine")
                        })
                
                if articles:
                    meta["articles"] = articles
            # ========================================

        
        
        elif root_tag == "ARTICLE":
            # Article metadata
            meta["id"] = root.find("META/META_COMMUN/ID").text if root.find("META/META_COMMUN/ID") is not None else None
            meta["num"] = root.find("META/META_COMMUN/NUM").text if root.find("META/META_COMMUN/NUM") is not None else None
            meta["origine"] = root.find("META/META_COMMUN/ORIGINE").text if root.find("META/META_COMMUN/ORIGINE") is not None else None
            
            # Dates validité
            meta_spec = root.find("META/META_SPEC")
            if meta_spec is not None:
                date_debut = meta_spec.find("META_ARTICLE/DATE_DEBUT")
                date_fin = meta_spec.find("META_ARTICLE/DATE_FIN")
                meta["date_debut"] = date_debut.text if date_debut is not None else None
                meta["date_fin"] = date_fin.text if date_fin is not None else None
            
            # Parent section/code
            parent_elem = root.find("CONTEXTE/TEXTE/TITRE_TXT")
            if parent_elem is not None:
                meta["parent"] = parent_elem.get("id")
            else:
                # Fallback : chercher dans LIENS
                lien_parent = root.find(".//LIEN[@typelien='PARENT']")
                if lien_parent is not None:
                    meta["parent"] = lien_parent.get("id")
            
            # Liens juridiques
            liens = root.find("LIENS")
            if liens is not None:
                meta["has_links"] = True
                link_types = {}
                for lien in liens:
                    ltype = lien.get("sens", "unknown")
                    link_types[ltype] = link_types.get(ltype, 0) + 1
                meta["link_types"] = link_types
            else:
                meta["has_links"] = False
        
        elif root_tag == "TEXTELR":
            # Texte structure (root of code)
            meta["id"] = root.find("META/META_COMMUN/ID").text if root.find("META/META_COMMUN/ID") is not None else None
            meta["nature"] = root.find("META/META_COMMUN/NATURE").text if root.find("META/META_COMMUN/NATURE") is not None else None
        
        return text, meta
    except Exception as e:
        return "", {"parse_error": True, "error": str(e)}


def _doc_id(source: str, path_in_tar: str, xml_bytes: Optional[bytes] = None, meta: Optional[dict] = None) -> str:
    """Generate a stable document id.

    Priority 1: Use LEGI ID from metadata (ensures logical uniqueness)
    Priority 2: Extract ID from path (e.g., LEGITEXT000006070721, LEGIARTI000006797825)
    Priority 3: Fallback to hash(source:path_in_tar) for compatibility
    
    This fixes the duplicate bug where timestamps in path caused infinite accumulation.
    """
    # Priorité 1 : Utiliser l'ID LEGI depuis metadata
    if meta and meta.get('id'):
        return meta['id']
    
    # Priorité 2 : Extraire ID LEGI depuis le path
    # Formats: LEGITEXT000006070721, LEGIARTI000006797825, LEGISCTA000006136117, etc.
    legi_id_match = re.search(r'(LEGI[A-Z]{3,4}\d{12})', path_in_tar)
    if legi_id_match:
        return legi_id_match.group(1)
    
    # Priorité 3 : Fallback sur path stable (sans timestamp)
    # Retirer le timestamp au début: "20260104-202823/legi/..." → "legi/..."
    stable_path = re.sub(r'^\d{8}-\d{6}/', '', path_in_tar)
    base = f"{source}:{stable_path}".encode("utf-8", errors="ignore")
    return hashlib.sha256(base).hexdigest()


def _parse_suppression_list(data: bytes) -> List[str]:
    """Parse liste_suppression_*.dat.

    Unknown exact format. MVP: each non-empty line is treated as an identifier key.
    We will delete documents where meta contains that id OR path contains it.

    Returns list of tokens.
    """
    lines = []
    for raw in data.decode("utf-8", errors="ignore").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        lines.append(s)
    return lines


def _db_connect() -> psycopg.Connection:
    return psycopg.connect(**DEFAULT_DB)


def _upsert_documents(conn: psycopg.Connection, rows: List[Tuple]) -> None:
    """Bulk upsert into documents.

    Row: (id, source, doctype, path, updated_at, sha256, meta_json, content_xml, content_text)
    """
    if not rows:
        return
    sql = """
    INSERT INTO documents (id, source, doctype, path, updated_at, sha256, meta, content_xml, content_text)
    VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
    ON CONFLICT (id) DO UPDATE SET
      source=EXCLUDED.source,
      doctype=EXCLUDED.doctype,
      path=EXCLUDED.path,
      updated_at=EXCLUDED.updated_at,
      sha256=EXCLUDED.sha256,
      meta=EXCLUDED.meta,
      content_xml=EXCLUDED.content_xml,
      content_text=EXCLUDED.content_text;
    """
    with conn.cursor() as cur:
        cur.executemany(sql, rows)


def _delete_by_tokens(conn: psycopg.Connection, tokens: List[str], source: str) -> int:
    """Delete docs matching suppression tokens - OPTIMIZED VERSION.
    
    Extracts IDs from paths and uses direct ID lookup with index instead of ILIKE.
    Fallback to ILIKE for tokens without valid IDs.
    """
    import re
    import time
    
    if not tokens:
        return 0
    
    start_time = time.time()
    
    # Extract IDs from tokens
    ids_to_delete = []
    tokens_without_id = []
    
    for token in tokens[:5000]:  # safety cap
        # Try to extract LEGI ID (LEGITEXT, LEGIARTI, LEGISCTA, etc.)
        match = re.search(r'(LEGI[A-Z]{3,5}\d{12})', token)
        if match:
            ids_to_delete.append(match.group(1))
        else:
            tokens_without_id.append(token)
    
    total_deleted = 0
    
    # Method 1: DELETE by ID (FAST - uses GIN index on meta->>'id')
    if ids_to_delete:
        batch_size = 1000
        for i in range(0, len(ids_to_delete), batch_size):
            batch = ids_to_delete[i:i+batch_size]
            
            sql = """
                DELETE FROM documents
                WHERE source = %s
                  AND meta->>'id' = ANY(%s)
            """
            
            with conn.cursor() as cur:
                cur.execute(sql, (source, batch))
                total_deleted += cur.rowcount
    
    # Method 2: Fallback to ILIKE for tokens without ID (SLOW but rare)
    if tokens_without_id:
        patterns = [f"%{t}%" for t in tokens_without_id]
        
        sql = """
            DELETE FROM documents
            WHERE source = %s
              AND (
                path ILIKE ANY(%s)
                OR meta::text ILIKE ANY(%s)
              )
        """
        
        with conn.cursor() as cur:
            cur.execute(sql, (source, patterns, patterns))
            total_deleted += cur.rowcount
    
    duration = time.time() - start_time
    print(f"[DELETE] {total_deleted} docs deleted in {duration:.2f}s ({total_deleted/duration if duration > 0 else 0:.1f} del/sec)")
    
    return total_deleted



def ingest_archive(
    conn: psycopg.Connection,
    source: str,
    archive_path: Path,
    logger: logging.Logger,
    updated_at: str,
    batch_size: int = 500,
) -> Dict[str, int]:
    """Ingest one .tar.gz archive."""
    source = source.upper()
    do_inserts = 0
    do_deletes = 0
    files_seen = 0

    pending: List[Tuple] = []

    # Streaming tar
    with gzip.open(archive_path, "rb") as gz:
        with tarfile.open(fileobj=gz, mode="r|*") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                files_seen += 1
                f = tar.extractfile(member)
                if f is None:
                    continue
                data = f.read()  # note: member sizes are typically manageable; streaming per file

                path_in_tar = member.name
                doctype = _guess_doctype(path_in_tar)

                if doctype == "suppression_list":
                    tokens = _parse_suppression_list(data)
                    deleted = _delete_by_tokens(conn, tokens, source)
                    do_deletes += deleted
                    conn.commit()
                    logger.info(f"Applied suppression list: {member.name} -> deleted={deleted}")
                    continue

                if doctype in ("article", "texte", "section", "xml") and path_in_tar.lower().endswith(".xml"):
                    text, meta = _extract_text_and_meta_from_xml(data, path_in_tar)
                    meta.update({"source": source})

                    doc_id = _doc_id(source, path_in_tar, meta=meta)
                    sha256 = _sha256_bytes(data)

                    pending.append(
                        (
                            doc_id,
                            source,
                            doctype,
                            path_in_tar,
                            updated_at,
                            sha256,
                            json.dumps(meta, ensure_ascii=False),
                            data.decode("utf-8", errors="replace"),
                            text,
                        )
                    )

                    if len(pending) >= batch_size:
                        _upsert_documents(conn, pending)
                        conn.commit()
                        do_inserts += len(pending)
                        pending.clear()

                # ignore other files for MVP

    if pending:
        _upsert_documents(conn, pending)
        conn.commit()
        do_inserts += len(pending)
        pending.clear()

    return {"files_seen": files_seen, "upserts": do_inserts, "deletes": do_deletes}


def run(mode: str, sources: List[str]) -> int:
    logger = _setup_logging()

    try:
        _acquire_lock()
    except FileExistsError:
        logger.error(f"Lock exists: {LOCK_PATH}")
        return 2

    try:
        if mode == "daily":
            # Safety: require init done
            st = _load_state()
            missing = [s for s in sources if not st.get("sources", {}).get(s, {}).get("initialized")]
            if missing:
                logger.error(f"Daily requested but sources not initialized: {missing}. Run --init first.")
                return 3

        state = _load_state()
        state.setdefault("sources", {})

        with _db_connect() as conn:
            for source in sources:
                source = source.upper()
                state["sources"].setdefault(source, {})

                archives = _iter_archives(source, mode)
                if mode == "daily" and not archives:
                    logger.info(f"{source}: no new incrementals to ingest")
                    continue

                logger.info(f"--- {source} ({mode}) ---")
                logger.info(f"Archives to ingest: {len(archives)}")

                for a in archives:
                    updated_at = _date_key(a)
                    logger.info(f"Ingesting {a.name} (updated_at={updated_at})")
                    stats = ingest_archive(conn, source, a, logger, updated_at=updated_at)
                    logger.info(f"Done {a.name}: {stats}")

                    # update state
                    if "incremental" in a.parent.name:
                        state["sources"][source]["last_incremental"] = a.name

                    # mark init
                    if mode == "init":
                        state["sources"][source]["initialized"] = True

                    state["sources"][source]["updated_at"] = datetime.now().isoformat()
                    state["updated_at"] = datetime.now().isoformat()
                    _save_state(state)

        return 0

    finally:
        _release_lock()


def main() -> int:
    ap = argparse.ArgumentParser(description="Ingest Legifrance archives into PostgreSQL")
    m = ap.add_mutually_exclusive_group(required=True)
    m.add_argument("--init", action="store_true")
    m.add_argument("--daily", action="store_true")

    ap.add_argument(
        "--sources",
        default="LEGI,JORF",
        help="Comma-separated sources (default: LEGI,JORF)",
    )

    args = ap.parse_args()
    sources = [s.strip().upper() for s in args.sources.split(",") if s.strip()]

    mode = "init" if args.init else "daily"
    return run(mode, sources)


if __name__ == "__main__":
    raise SystemExit(main())
