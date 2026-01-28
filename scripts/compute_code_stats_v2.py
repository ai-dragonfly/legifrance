#!/usr/bin/env python3
"""Calcule statistiques codes LEGI (VERSION OPTIMISÉE).

Stratégie B : GROUP BY avec extraction regex au lieu de LIKE '%LEGITEXT%'.

Temps estimé : 30-60 min (vs 47 jours v1)
Gain : 2000x plus rapide

Usage:
  compute_code_stats_v2.py [--verbose]
"""

import argparse
import sys
import psycopg
from datetime import datetime

# Config DB (peer auth)
DB_CONFIG = {
    "dbname": "legifrance",
    "user": "legifrance_app",
    "host": "/var/run/postgresql"
}


def db_connect():
    """Connect to PostgreSQL."""
    return psycopg.connect(**DB_CONFIG)


def compute_all_stats(conn, verbose: bool = False):
    """Calcule toutes les statistiques en 2 requêtes GROUP BY.
    
    Returns:
        dict: {code_id: {"nb_articles": X, "nb_sections": Y}}
    """
    stats = {}
    
    if verbose:
        print("📊 Calcul statistiques articles...")
    
    with conn.cursor() as cur:
        # 1. Compter articles par code (1 seul scan)
        # FIX: Mettre l'expression dans GROUP BY
        cur.execute("""
            SELECT 
                code_id,
                COUNT(*) as nb
            FROM (
                SELECT (regexp_match(path, '/TEXT/[0-9/]+/(LEGITEXT[0-9]+)/'))[1] as code_id
                FROM documents
                WHERE source = 'LEGI' 
                  AND doctype = 'article'
                  AND path ~ '/TEXT/[0-9/]+/LEGITEXT[0-9]+/'
            ) AS subquery
            WHERE code_id IS NOT NULL
              AND code_id IN (
                  SELECT DISTINCT meta->>'id'
                  FROM documents
                  WHERE source = 'LEGI'
                    AND doctype = 'texte'
                    AND meta->>'etat' IN ('VIGUEUR', 'ABROGE')
                    AND meta->>'id' IS NOT NULL
              )
            GROUP BY code_id
        """)
        
        for code_id, nb in cur.fetchall():
            if code_id not in stats:
                stats[code_id] = {"nb_articles": 0, "nb_sections": 0}
            stats[code_id]["nb_articles"] = nb
        
        if verbose:
            print(f"   ✅ {len(stats)} codes avec articles")
    
    if verbose:
        print("📊 Calcul statistiques sections...")
    
    with conn.cursor() as cur:
        # 2. Compter sections par code (1 seul scan)
        cur.execute("""
            SELECT 
                meta->>'parent' as code_id,
                COUNT(*) as nb
            FROM documents
            WHERE source = 'LEGI' 
              AND doctype = 'section'
              AND meta->>'parent' IS NOT NULL
              AND meta->>'parent' LIKE 'LEGITEXT%'
              AND meta->>'parent' IN (
                  SELECT DISTINCT meta->>'id'
                  FROM documents
                  WHERE source = 'LEGI'
                    AND doctype = 'texte'
                    AND meta->>'etat' IN ('VIGUEUR', 'ABROGE')
                    AND meta->>'id' IS NOT NULL
              )
            GROUP BY meta->>'parent'
        """)
        
        for code_id, nb in cur.fetchall():
            if code_id not in stats:
                stats[code_id] = {"nb_articles": 0, "nb_sections": 0}
            stats[code_id]["nb_sections"] = nb
        
        if verbose:
            print(f"   ✅ {len(stats)} codes avec sections")
    
    return stats


def fetch_all_texts(conn, code_ids: list):
    """Récupère métadonnées des textes (codes/TNC).
    
    Args:
        conn: Connexion PostgreSQL
        code_ids: Liste des code_ids à récupérer
        
    Returns:
        dict: {code_id: {"titre": X, "nature": Y, "etat": Z}}
    """
    with conn.cursor() as cur:
        # Batch query avec IN pour éviter trop de roundtrips
        placeholders = ','.join(['%s'] * len(code_ids))
        
        # FIX: Inclure AUSSI doctype='texte' (pas seulement 'texte_version')
        cur.execute(f"""
            SELECT DISTINCT ON (meta->>'id')
                meta->>'id' as id,
                meta->>'titre' as titre,
                meta->>'nature' as nature,
                CASE
                    WHEN meta->>'etat' = 'VIGUEUR' THEN 'VIGUEUR'
                    WHEN meta->>'etat' = 'ABROGE' THEN 'ABROGE'
                    WHEN meta->>'date_fin' IS NULL THEN 'VIGUEUR'
                    WHEN meta->>'date_fin' >= '2999-01-01' THEN 'VIGUEUR'
                    ELSE NULL
                END as etat
            FROM documents
            WHERE source = 'LEGI'
              AND (doctype = 'texte_version' OR doctype = 'texte')
              AND meta->>'id' IN ({placeholders})
              AND meta->>'titre' IS NOT NULL
              AND meta->>'titre' != ''
              AND meta->>'etat' IN ('VIGUEUR', 'ABROGE')
            ORDER BY meta->>'id', meta->>'date_debut' DESC NULLS LAST
        """, code_ids)
        
        texts = {}
        for row in cur.fetchall():
            code_id, titre, nature, etat = row
            if code_id:
                texts[code_id] = {
                    "titre": titre or f"Texte {code_id}",
                    "nature": nature or "TEXTE",
                    "etat": etat
                }
        
        return texts


def upsert_code_stats(conn, code_id: str, titre: str, nature: str, etat: str, 
                      nb_articles: int, nb_sections: int):
    """Upsert dans table code_stats.
    
    Args:
        conn: Connexion PostgreSQL
        code_id: ID du code (LEGITEXT...)
        titre: Titre du code
        nature: Nature (CODE, DECRET, etc.)
        etat: Etat (VIGUEUR, ABROGE)
        nb_articles: Nombre d'articles
        nb_sections: Nombre de sections
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO code_stats 
                (code_id, titre, nature, etat, nb_articles, nb_sections, updated_at)
            VALUES 
                (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (code_id) DO UPDATE SET
                titre = EXCLUDED.titre,
                nature = EXCLUDED.nature,
                etat = EXCLUDED.etat,
                nb_articles = EXCLUDED.nb_articles,
                nb_sections = EXCLUDED.nb_sections,
                updated_at = NOW()
        """, (code_id, titre, nature, etat, nb_articles, nb_sections))


def main():
    parser = argparse.ArgumentParser(description="Calcule statistiques codes LEGI (v2 optimisée)")
    parser.add_argument('--verbose', '-v', action='store_true', 
                        help='Mode verbose')
    
    args = parser.parse_args()
    
    start_time = datetime.now()
    print(f"[{start_time.strftime('%Y-%m-%d %H:%M:%S')}] 🚀 Début calcul statistiques codes LEGI (v2 optimisée)")
    print("   Stratégie : GROUP BY avec extraction regex")
    print("   Temps estimé : 30-60 min")
    print()
    
    try:
        conn = db_connect()
        
        # 1. Calculer statistiques (2 GROUP BY)
        print("📊 Phase 1 : Calcul statistiques (2 scans complets)...")
        stats = compute_all_stats(conn, verbose=args.verbose)
        print(f"   ✅ {len(stats)} codes trouvés avec stats\n")
        
        # 2. Récupérer métadonnées textes
        print("📋 Phase 2 : Récupération métadonnées textes...")
        code_ids = list(stats.keys())
        texts = fetch_all_texts(conn, code_ids)
        print(f"   ✅ {len(texts)} textes récupérés\n")
        
        # 3. Upsert dans code_stats
        print("💾 Phase 3 : Mise à jour table code_stats...")
        processed = 0
        errors = 0
        
        for code_id in code_ids:
            try:
                # Récupérer métadonnées (si disponibles)
                text_meta = texts.get(code_id, {
                    "titre": f"Texte {code_id}",
                    "nature": "TEXTE",
                    "etat": "VIGUEUR"
                })
                
                # Upsert
                upsert_code_stats(
                    conn,
                    code_id,
                    text_meta["titre"],
                    text_meta["nature"],
                    text_meta["etat"],
                    stats[code_id]["nb_articles"],
                    stats[code_id]["nb_sections"]
                )
                
                processed += 1
                
                if processed % 1000 == 0 and args.verbose:
                    print(f"   ⏳ {processed}/{len(code_ids)} codes traités...")
                
            except Exception as e:
                errors += 1
                print(f"   ❌ Erreur sur {code_id}: {e}", file=sys.stderr)
                continue
        
        conn.commit()
        conn.close()
        
        # 4. Résumé
        duration = (datetime.now() - start_time).total_seconds()
        print(f"\n✅ Terminé en {duration:.1f}s ({duration/60:.1f} min)")
        print(f"   📊 {processed} codes traités")
        print(f"   ❌ {errors} erreurs")
        
        # Statistiques finales
        print("\n📈 Statistiques finales :")
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT 
                        COUNT(*) as total,
                        COUNT(*) FILTER (WHERE nature ILIKE '%CODE%' OR titre ILIKE '%code%') as codes,
                        COUNT(*) FILTER (WHERE etat = 'VIGUEUR') as en_vigueur,
                        COUNT(*) FILTER (WHERE etat = 'ABROGE') as abroges
                    FROM code_stats
                """)
                total, codes, vigueur, abroges = cur.fetchone()
                print(f"   📚 Total textes : {total}")
                print(f"   📕 Codes (filtre titre/nature) : {codes}")
                print(f"   ✅ En vigueur : {vigueur}")
                print(f"   ⚠️  Abrogés : {abroges}")
        
        if errors > 0:
            sys.exit(1)
        else:
            sys.exit(0)
    
    except Exception as e:
        print(f"\n❌ ERREUR FATALE: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
