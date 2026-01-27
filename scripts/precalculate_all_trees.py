#!/usr/bin/env python3
"""Script OPTIMISÉ de pré-calcul des arborescences complètes (depth=10) pour tous les codes LEGI.

Version 2 - OPTIMISATION MAJEURE :
- 2-3 requêtes SQL au lieu de 35K
- Construction de l'arbre en mémoire (pas de récursion SQL)
- Exploitation des données JSON sous_sections/articles déjà extraites
- Performance : ~2-5 min par code (vs 30-90 min avant)

Principe :
1. Charger toutes les sections nécessaires en UNE fois (par vagues)
2. Construire l'arbre en Python en suivant les IDs JSON
3. Sauvegarder en cache

Usage:
    python3 precalculate_all_trees.py [--limit N] [--code-id LEGITEXT...]
"""

import argparse
import json
import sys
import time
from typing import List, Dict, Optional, Set
import psycopg

# Config DB
DB_CONFIG = {
    "dbname": "legifrance",
    "user": "legifrance_app",
    "host": "/var/run/postgresql"
}


def db_connect():
    """Connect to PostgreSQL."""
    return psycopg.connect(**DB_CONFIG)


def get_all_code_ids(limit: Optional[int] = None) -> List[Dict]:
    """Récupère la liste de tous les codes LEGI."""
    with db_connect() as conn:
        with conn.cursor() as cur:
            sql = """
            SELECT 
                code_id,
                titre,
                nature,
                nb_sections,
                nb_articles
            FROM code_stats
            WHERE (nature ILIKE '%CODE%' OR titre ILIKE '%code%')
              AND etat = 'VIGUEUR'
            ORDER BY nb_sections DESC, nb_articles DESC
            """
            
            if limit:
                sql += f" LIMIT {limit}"
            
            cur.execute(sql)
            
            codes = []
            for row in cur.fetchall():
                codes.append({
                    "code_id": row[0],
                    "titre": row[1],
                    "nature": row[2],
                    "nb_sections": row[3] or 0,
                    "nb_articles": row[4] or 0
                })
            
            return codes


def build_tree_optimized(code_id: str) -> Dict:
    """Construction OPTIMISÉE de l'arbre depth=10.
    
    Stratégie :
    1. Charger sections racines
    2. Collecter tous les IDs de sous-sections (récursif en mémoire)
    3. Charger toutes ces sections en UNE requête
    4. Construire l'arbre en Python
    """
    with db_connect() as conn:
        with conn.cursor() as cur:
            # 1. Récupérer infos code
            cur.execute("""
                SELECT meta->>'titre', meta->>'nature'
                FROM documents
                WHERE source = 'LEGI'
                  AND doctype = 'texte'
                  AND meta->>'id' = %s
                LIMIT 1
            """, (code_id,))
            
            code_row = cur.fetchone()
            if not code_row:
                return None
            
            titre_code, nature = code_row
            
            # 2. Charger sections racines (déduplication)
            cur.execute("""
                SELECT DISTINCT ON (meta->>'id')
                    meta->>'id' as id,
                    meta->>'titre' as titre,
                    meta->'sous_sections' as sous_sections,
                    meta->'articles' as articles,
                    COALESCE(meta->>'nb_sections', '0')::int as nb_sections,
                    COALESCE(meta->>'nb_articles', '0')::int as nb_articles
                FROM documents
                WHERE source = 'LEGI'
                  AND doctype = 'section'
                  AND meta->>'parent' = %s
                ORDER BY meta->>'id',
                         COALESCE(meta->>'date_debut', '1900-01-01') DESC
            """, (code_id,))
            
            root_sections = {}
            root_ids = []
            
            for row in cur.fetchall():
                section_id = row[0]
                root_ids.append(section_id)
                root_sections[section_id] = {
                    "id": section_id,
                    "titre": row[1],
                    "sous_sections": row[2],
                    "articles": row[3],
                    "nb_sections": row[4],
                    "nb_articles": row[5]
                }
            
            # 3. Collecter TOUS les IDs de sous-sections (récursif en mémoire)
            all_needed_ids = set(root_ids)
            
            def collect_subsection_ids(section_data):
                """Collecte récursive des IDs depuis JSON."""
                if not section_data.get("sous_sections"):
                    return
                
                for ss in section_data["sous_sections"]:
                    ss_id = ss.get("id")
                    if ss_id and ss_id not in all_needed_ids:
                        all_needed_ids.add(ss_id)
            
            # Première passe : collecter depuis racines
            for section in root_sections.values():
                collect_subsection_ids(section)
            
            # 4. Charger TOUTES les sections nécessaires par vagues
            all_sections = dict(root_sections)  # Copie des racines
            remaining_ids = all_needed_ids - set(root_ids)
            
            max_waves = 10  # Limite profondeur
            wave_num = 0
            
            while remaining_ids and wave_num < max_waves:
                wave_num += 1
                
                # Charger cette vague d'IDs
                ids_list = list(remaining_ids)
                
                cur.execute("""
                    SELECT DISTINCT ON (meta->>'id')
                        meta->>'id' as id,
                        meta->>'titre' as titre,
                        meta->'sous_sections' as sous_sections,
                        meta->'articles' as articles,
                        COALESCE(meta->>'nb_sections', '0')::int as nb_sections,
                        COALESCE(meta->>'nb_articles', '0')::int as nb_articles
                    FROM documents
                    WHERE source = 'LEGI'
                      AND doctype = 'section'
                      AND meta->>'id' = ANY(%s)
                    ORDER BY meta->>'id',
                             COALESCE(meta->>'date_debut', '1900-01-01') DESC
                """, (ids_list,))
                
                new_sections = {}
                for row in cur.fetchall():
                    section_id = row[0]
                    new_sections[section_id] = {
                        "id": section_id,
                        "titre": row[1],
                        "sous_sections": row[2],
                        "articles": row[3],
                        "nb_sections": row[4],
                        "nb_articles": row[5]
                    }
                
                # Ajouter au dict global
                all_sections.update(new_sections)
                
                # Collecter nouveaux IDs depuis les nouvelles sections
                new_ids_to_fetch = set()
                for section in new_sections.values():
                    if section.get("sous_sections"):
                        for ss in section["sous_sections"]:
                            ss_id = ss.get("id")
                            if ss_id and ss_id not in all_sections and ss_id not in new_ids_to_fetch:
                                new_ids_to_fetch.add(ss_id)
                
                # Mettre à jour remaining_ids
                remaining_ids = new_ids_to_fetch
            
            # 5. Construction de l'arbre en MÉMOIRE (pas de SQL !)
            def build_node_from_memory(section_id: str, current_depth: int, max_depth: int) -> Optional[Dict]:
                """Construit un nœud depuis les données en mémoire."""
                if current_depth > max_depth:
                    return None
                
                if section_id not in all_sections:
                    return None
                
                section = all_sections[section_id]
                
                node = {
                    "id": section["id"],
                    "titre": section["titre"],
                    "nb_sections": section["nb_sections"],
                    "nb_articles": section["nb_articles"]
                }
                
                # Sous-sections (récursion EN MÉMOIRE)
                if current_depth < max_depth and section.get("sous_sections"):
                    children = []
                    for ss in section["sous_sections"]:
                        # Filtrer versions en vigueur
                        if ss.get('fin', '2999-01-01') == '2999-01-01' or ss.get('etat') == 'VIGUEUR':
                            child = build_node_from_memory(ss["id"], current_depth + 1, max_depth)
                            if child:
                                children.append(child)
                    
                    if children:
                        node["children"] = children
                
                # Articles (limiter à 500)
                if section.get("articles"):
                    articles_filtered = []
                    for art in section["articles"]:
                        if art.get('fin', '2999-01-01') == '2999-01-01' or art.get('etat') == 'VIGUEUR':
                            articles_filtered.append({
                                "id": art.get("id"),
                                "num": art.get("num"),
                                "titre": art.get("titre", "")
                            })
                            if len(articles_filtered) >= 500:
                                break
                    
                    if articles_filtered:
                        node["articles"] = articles_filtered
                
                return node
            
            # 6. Construire arbre depuis racines
            tree = []
            for root_id in root_ids:
                node = build_node_from_memory(root_id, current_depth=1, max_depth=10)
                if node:
                    tree.append(node)
            
            return {
                "code_id": code_id,
                "titre": titre_code or f"Code {code_id}",
                "nature": nature or "CODE",
                "tree": tree,
                "nb_sections_loaded": len(all_sections),
                "nb_waves": wave_num
            }


def count_sections_in_tree(tree: List[Dict]) -> int:
    """Compte le nombre de sections dans l'arbre."""
    count = len(tree)
    for node in tree:
        if "children" in node:
            count += count_sections_in_tree(node["children"])
    return count


def count_articles_in_tree(tree: List[Dict]) -> int:
    """Compte le nombre d'articles dans l'arbre."""
    count = 0
    for node in tree:
        if "articles" in node:
            count += len(node["articles"])
        if "children" in node:
            count += count_articles_in_tree(node["children"])
    return count


def save_to_cache(code_id: str, titre: str, nature: str, tree: List[Dict], 
                  generation_duration_ms: int, tree_size_bytes: int) -> None:
    """Sauvegarde l'arbre dans la table code_trees."""
    with db_connect() as conn:
        with conn.cursor() as cur:
            nb_sections = count_sections_in_tree(tree)
            nb_articles = count_articles_in_tree(tree)
            
            cur.execute("""
                INSERT INTO code_trees (
                    code_id, titre, nature, tree, 
                    nb_sections, nb_articles,
                    generation_duration_ms, tree_size_bytes,
                    version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '2.0')
                ON CONFLICT (code_id) DO UPDATE
                SET 
                    titre = EXCLUDED.titre,
                    nature = EXCLUDED.nature,
                    tree = EXCLUDED.tree,
                    nb_sections = EXCLUDED.nb_sections,
                    nb_articles = EXCLUDED.nb_articles,
                    generation_duration_ms = EXCLUDED.generation_duration_ms,
                    tree_size_bytes = EXCLUDED.tree_size_bytes,
                    updated_at = NOW(),
                    generated_at = NOW(),
                    version = '2.0'
            """, (code_id, titre, nature, json.dumps(tree), 
                  nb_sections, nb_articles, generation_duration_ms, tree_size_bytes))
            
            conn.commit()


def precalculate_all(limit: Optional[int] = None, code_id: Optional[str] = None, 
                     force: bool = False) -> None:
    """Pré-calcule tous les arbres."""
    
    # Récupérer liste codes
    if code_id:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT code_id, titre, nature, nb_sections, nb_articles
                    FROM code_stats
                    WHERE code_id = %s
                """, (code_id,))
                row = cur.fetchone()
                if not row:
                    print(f"❌ Code {code_id} not found")
                    return
                codes = [{
                    "code_id": row[0],
                    "titre": row[1],
                    "nature": row[2],
                    "nb_sections": row[3] or 0,
                    "nb_articles": row[4] or 0
                }]
    else:
        codes = get_all_code_ids(limit)
    
    total_codes = len(codes)
    print(f"\n🚀 Pré-calcul OPTIMISÉ de {total_codes} arbres depth=10")
    print(f"{'='*80}\n")
    
    success_count = 0
    error_count = 0
    skip_count = 0
    total_duration_ms = 0
    total_size_bytes = 0
    
    for idx, code in enumerate(codes, 1):
        code_id = code['code_id']
        titre = code['titre']
        nb_sections = code['nb_sections']
        nb_articles = code['nb_articles']
        
        # Vérifier si déjà en cache
        if not force:
            with db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 1 FROM code_trees 
                        WHERE code_id = %s 
                          AND updated_at > NOW() - INTERVAL '24 hours'
                          AND version = '2.0'
                    """, (code_id,))
                    if cur.fetchone():
                        print(f"[{idx}/{total_codes}] ⏭️  {code_id[:20]}... (cached v2.0, skip)")
                        skip_count += 1
                        continue
        
        print(f"[{idx}/{total_codes}] 🔨 {code_id[:20]}... ({nb_sections} sections, {nb_articles} articles)")
        print(f"               {titre[:60]}...")
        
        try:
            start = time.time()
            
            # Générer arbre OPTIMISÉ
            result = build_tree_optimized(code_id)
            
            if not result:
                print(f"               ❌ Code not found in DB")
                error_count += 1
                continue
            
            tree = result['tree']
            tree_json = json.dumps(tree)
            tree_size = len(tree_json.encode('utf-8'))
            duration_ms = int((time.time() - start) * 1000)
            
            # Sauvegarder en cache
            save_to_cache(code_id, result['titre'], result['nature'], 
                         tree, duration_ms, tree_size)
            
            # Stats
            nb_sections_tree = count_sections_in_tree(tree)
            nb_articles_tree = count_articles_in_tree(tree)
            nb_sections_loaded = result.get('nb_sections_loaded', 0)
            nb_waves = result.get('nb_waves', 0)
            
            print(f"               ✅ {duration_ms}ms | {tree_size/1024:.1f} KB | "
                  f"{nb_sections_tree} sections | {nb_articles_tree} articles")
            print(f"               📊 Loaded {nb_sections_loaded} sections in {nb_waves} waves")
            
            success_count += 1
            total_duration_ms += duration_ms
            total_size_bytes += tree_size
            
        except Exception as e:
            print(f"               ❌ ERROR: {e}")
            import traceback
            traceback.print_exc()
            error_count += 1
        
        print()
    
    # Résumé final
    print(f"{'='*80}")
    print(f"\n✅ TERMINÉ : {success_count}/{total_codes} codes pré-calculés")
    print(f"⏭️  SKIP : {skip_count} (déjà en cache v2.0)")
    print(f"❌ ERREURS : {error_count}")
    
    if success_count > 0:
        avg_duration = total_duration_ms / success_count
        avg_size = total_size_bytes / success_count
        print(f"\n📊 STATS MOYENNES :")
        print(f"   - Temps génération : {avg_duration:.0f}ms par code ({avg_duration/1000:.1f}s)")
        print(f"   - Taille cache : {avg_size/1024:.1f} KB par code")
        print(f"   - Taille totale : {total_size_bytes/1024/1024:.1f} MB")
    
    print(f"\n🕐 Durée totale : {total_duration_ms/1000/60:.1f} minutes")


def main():
    parser = argparse.ArgumentParser(description="Pré-calcul OPTIMISÉ arbres depth=10 pour codes LEGI")
    parser.add_argument('--limit', type=int, help='Limiter à N codes (pour tests)')
    parser.add_argument('--code-id', help='Générer uniquement ce code (LEGITEXT...)')
    parser.add_argument('--force', action='store_true', help='Régénérer même si déjà en cache')
    
    args = parser.parse_args()
    
    try:
        precalculate_all(limit=args.limit, code_id=args.code_id, force=args.force)
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ ERREUR CRITIQUE : {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
