#!/usr/bin/env python3
"""Régénération automatique des caches obsolètes (codes modifiés dernières 24h).

Phase 4d - Maintenance Cache
- Détecte codes avec cache invalidé (updated_at < NOW() - 24h)
- Régénère uniquement ceux-là
- Durée attendue : 5-15 min/jour (selon nb codes modifiés)

Usage:
    python3 regenerate_stale_caches.py [--force] [--limit N]
    
Options:
    --force   : Régénérer tous les codes (ignore updated_at)
    --limit N : Limiter à N codes (pour tests)
    
Intégration:
    Appelé par daily_pipeline.py (Step 5) après compute_code_stats
"""

import argparse
import json
import sys
import time
import subprocess
from pathlib import Path
from typing import List, Dict
import psycopg

# Config DB (peer auth)
DB_CONFIG = {
    "dbname": "legifrance",
    "user": "legifrance_app",
    "host": "/var/run/postgresql"
}

SCRIPT_DIR = Path(__file__).parent
PRECALCULATE_SCRIPT = SCRIPT_DIR / "precalculate_all_trees.py"


def db_connect():
    """Connect to PostgreSQL."""
    return psycopg.connect(**DB_CONFIG)


def get_stale_codes(force: bool = False, limit: int = None) -> List[Dict]:
    """Récupère codes avec cache obsolète.
    
    Args:
        force: Si True, retourne tous les codes (ignore updated_at)
        limit: Limiter à N codes
        
    Returns:
        Liste de dicts avec code_id, titre, updated_at
    """
    with db_connect() as conn:
        with conn.cursor() as cur:
            if force:
                # Mode force : tous les codes
                sql = """
                SELECT 
                    code_id,
                    titre,
                    updated_at,
                    NOW() - updated_at as age
                FROM code_trees
                ORDER BY updated_at ASC
                """
            else:
                # Mode normal : seulement codes obsolètes (>24h)
                sql = """
                SELECT 
                    code_id,
                    titre,
                    updated_at,
                    NOW() - updated_at as age
                FROM code_trees
                WHERE updated_at < NOW() - INTERVAL '24 hours'
                ORDER BY updated_at ASC
                """
            
            if limit:
                sql += f" LIMIT {limit}"
            
            cur.execute(sql)
            
            codes = []
            for row in cur.fetchall():
                codes.append({
                    "code_id": row[0],
                    "titre": row[1],
                    "updated_at": row[2],
                    "age": str(row[3]) if row[3] else None
                })
            
            return codes


def regenerate_code(code_id: str) -> bool:
    """Régénère cache pour un code en appelant precalculate_all_trees.py.
    
    Args:
        code_id: ID du code à régénérer
        
    Returns:
        True si succès, False si erreur
    """
    try:
        cmd = [
            "python3",
            str(PRECALCULATE_SCRIPT),
            "--code-id", code_id,
            "--force"
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300  # 5 min max par code
        )
        
        if result.returncode == 0:
            return True
        else:
            print(f"   ❌ Erreur : {result.stderr[:200]}", file=sys.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print(f"   ⏱️  Timeout après 5 minutes", file=sys.stderr)
        return False
    except Exception as e:
        print(f"   ❌ Exception : {e}", file=sys.stderr)
        return False


def get_invalidation_stats() -> Dict:
    """Récupère statistiques invalidations dernières 24h."""
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    reason,
                    COUNT(*) as count
                FROM cache_invalidations
                WHERE triggered_at > NOW() - INTERVAL '24 hours'
                GROUP BY reason
                ORDER BY count DESC
            """)
            
            stats = {}
            for row in cur.fetchall():
                stats[row[0]] = row[1]
            
            return stats


def main():
    parser = argparse.ArgumentParser(
        description="Régénération automatique des caches obsolètes"
    )
    parser.add_argument('--force', action='store_true', 
                       help='Régénérer tous les codes (ignore updated_at)')
    parser.add_argument('--limit', type=int, 
                       help='Limiter à N codes (pour tests)')
    parser.add_argument('--verbose', action='store_true',
                       help='Afficher logs détaillés')
    
    args = parser.parse_args()
    
    print("\n" + "="*80)
    print("🔄 RÉGÉNÉRATION CACHES OBSOLÈTES")
    print("="*80 + "\n")
    
    # Statistiques invalidations
    if not args.force:
        stats = get_invalidation_stats()
        if stats:
            print("📊 Invalidations dernières 24h :")
            for reason, count in stats.items():
                print(f"   - {reason}: {count}")
            print()
    
    # Récupérer codes obsolètes
    start_time = time.time()
    stale_codes = get_stale_codes(force=args.force, limit=args.limit)
    
    if not stale_codes:
        print("✅ Aucun cache obsolète détecté\n")
        return 0
    
    # Afficher liste
    print(f"🔨 {len(stale_codes)} code(s) à régénérer :\n")
    
    if args.verbose:
        for code in stale_codes[:10]:  # Max 10 dans logs
            age = code.get('age', 'N/A')
            print(f"   - {code['code_id']}: {code['titre'][:50]}... (age: {age})")
        if len(stale_codes) > 10:
            print(f"   ... et {len(stale_codes) - 10} autres")
        print()
    
    # Régénérer chaque code
    success_count = 0
    error_count = 0
    
    for idx, code in enumerate(stale_codes, 1):
        code_id = code['code_id']
        titre = code['titre'][:40]
        
        print(f"[{idx}/{len(stale_codes)}] 🔨 {code_id} ({titre}...)", end=" ", flush=True)
        
        if regenerate_code(code_id):
            print("✅")
            success_count += 1
        else:
            print("❌")
            error_count += 1
    
    # Résumé
    elapsed = time.time() - start_time
    
    print("\n" + "="*80)
    print(f"✅ TERMINÉ en {elapsed:.1f}s")
    print(f"   - Succès : {success_count}/{len(stale_codes)}")
    if error_count > 0:
        print(f"   - Erreurs : {error_count}")
    print("="*80 + "\n")
    
    # Exit code
    if error_count > 0:
        return 1  # Erreurs non-fatales
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  Interrompu par l'utilisateur", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ ERREUR CRITIQUE : {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
