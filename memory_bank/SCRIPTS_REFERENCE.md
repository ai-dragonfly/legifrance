# SCRIPTS_REFERENCE — Contrats des scripts serveur

## Principes
Chaque script doit :
- fonctionner en mode foreground et background
- écrire des logs horodatés
- gérer un lockfile si risque de double run
- gérer un state file si job long / reprise

---

## `download_archives.py`
### Rôle
Télécharge les archives DILA par source.

### Entrées
- DILA listing : `https://echanges.dila.gouv.fr/OPENDATA/<SOURCE>/`

### Sorties
- Archives : `/root/legifrance/archives/<SOURCE>/{freemium|incremental}/*.tar.gz`
- State : `/root/legifrance/config/download_state.json`
- Logs : `/root/legifrance/logs/download_*.log`

### Commandes
- `--all` (init)
- `--incremental` (quotidien)
- `--freemium` (init)
- `--status`

### Version
**v1.0** (stable depuis 25 jan 2026)

---

## `check_integrity.py`
### Rôle
- Compare listing distant vs local (manquants)
- Vérifie corruption via `gzip -t`
- Auto-fix : suppression corrompus + relance download (si activé)

### Sorties
- Report : `/root/legifrance/config/integrity_report_*.json`
- Logs : `/root/legifrance/logs/integrity_*.log`
- Lock : `/tmp/legifrance_integrity.lock`

### Commandes
- `--auto-fix` : supprime archives corrompues
- `--relaunch-download` : relance téléchargement après suppression

### Version
**v1.0** (stable depuis 25 jan 2026)

---

## `ingest_legifrance_pg.py` ⭐ v3.1 (27 jan 2026)
### Rôle
Ingestion streaming des archives vers PostgreSQL avec hiérarchie complète.

### Fonctionnalités
- Lecture streaming tar.gz (évite extraction filesystem)
- Parsing XML avec lxml (extraction métadonnées structurées)
- Upsert dans table `documents` (INSERT ON CONFLICT)
- **DELETE optimisé** : Extraction ID regex + DELETE par batch sur `meta->>'id'` (Gain 100x)
- **STRUCTURE_TA** : Extraction sous-sections et articles (v3.0)
- **Clé primaire intelligente** : `meta->>'id'` + extraction path + hash stable (v3.1)

### Entrées
- Archives : `/root/legifrance/archives/<SOURCE>/{freemium|incremental}/*.tar.gz`

### Sorties
- PostgreSQL : table `documents` dans DB `legifrance`
- State : `/root/legifrance/config/ingest_state.json`
- Logs : `/root/legifrance/logs/ingest_pg_*.log`
- Lock : `/tmp/legifrance_ingest.lock`

### Commandes
- `--init --sources LEGI,JORF` : freemium + tous incrementals
- `--daily --sources LEGI,JORF` : seulement nouveaux incrementals

### Structure métadonnées extraites (v3.1)

#### **TEXTE_VERSION** (codes/TNC)
- `id`, `titre`, `nature`, `etat`, `date_debut`, `date_fin`

#### **SECTION_TA** (sections)
- `id`, `titre`, `parent`, `nb_sections`, `nb_articles`
- **`sous_sections`** : Array JSONB avec IDs sous-sections (STRUCTURE_TA)
- **`articles`** : Array JSONB avec IDs articles (STRUCTURE_TA)

#### **ARTICLE** (articles)
- `id`, `num`, `origine`, `date_debut`, `date_fin`, `has_links`, `link_types`

### Fonction `_doc_id()` (v3.1 - correction bug doublons)

```python
def _doc_id(source: str, path_in_tar: str, xml_bytes: Optional[bytes] = None, 
            meta: Optional[dict] = None) -> str:
    """Generate a stable document id.
    
    Priority 1: Use LEGI ID from metadata (ensures logical uniqueness)
    Priority 2: Extract ID from path (e.g., LEGITEXT000006070721)
    Priority 3: Fallback to hash(source:stable_path) for compatibility
    
    v3.1: Fixes duplicate bug where timestamps in path caused infinite accumulation.
    """
    # Priorité 1 : ID LEGI depuis metadata
    if meta and meta.get('id'):
        return meta['id']
    
    # Priorité 2 : Extraction ID depuis path (regex)
    legi_id_match = re.search(r'(LEGI[A-Z]{3,4}\d{12})', path_in_tar)
    if legi_id_match:
        return legi_id_match.group(1)
    
    # Priorité 3 : Hash path STABLE (sans timestamp)
    stable_path = re.sub(r'^\d{8}-\d{6}/', '', path_in_tar)
    base = f"{source}:{stable_path}".encode("utf-8", errors="ignore")
    return hashlib.sha256(base).hexdigest()
```

### Performance
- **58 secondes/archive** (moyenne)
- **520 docs/seconde** (freemium)
- **DELETE** : 100x plus rapide (extraction regex ID)

### Versions
- **v1.0** (25 jan) : MVP streaming + parsing basique
- **v2.0** (26 jan) : DELETE optimisé
- **v3.0** (26 jan) : STRUCTURE_TA (sous_sections + articles)
- **v3.1** (27 jan) : Clé primaire intelligente (fix doublons)

---

## `compute_code_stats_v2.py` ⭐ v2.3 (27 jan 2026)

### Rôle
Pré-calcul statistiques codes pour accélération CLI.

### Fonctionnalités
- Utilise **Stratégie GROUP BY globale** (au lieu de boucler sur chaque texte)
- Calcule nombre d'articles et sections pour tous les codes
- **Filtre codes MODIFIE** (v2.2) : Ne traite que VIGUEUR et ABROGE
- **Filtre orphelins** (v2.3) : Ne compte que articles/sections avec parent valide
- Upsert dans table `code_stats`

### Sorties
- Table `code_stats` mise à jour (~2,967 codes)
- Logs : stdout

### Commandes
- `--verbose` : affiche progression détaillée

### Durée
- **52 secondes** pour 2,967 codes (Gain 8,500x vs v1)
- Doit être lancé après chaque ingestion

### Phase 1 : Comptage articles/sections (v2.3)

```sql
-- Articles : extraction ID depuis path + filtre parent valide
SELECT code_id, COUNT(*) as nb
FROM (
    SELECT (regexp_match(path, '/TEXT/[0-9/]+/(LEGITEXT[0-9]+)/'))[1] as code_id
    FROM documents
    WHERE source = 'LEGI' 
      AND doctype = 'article'
      AND path ~ '/TEXT/[0-9/]+/LEGITEXT[0-9]+/'
) AS subquery
WHERE code_id IN (
    SELECT DISTINCT meta->>'id' FROM documents
    WHERE source = 'LEGI' AND doctype = 'texte'
      AND meta->>'etat' IN ('VIGUEUR', 'ABROGE')
)
GROUP BY code_id
```

```sql
-- Sections : utilise meta->>'parent' + filtre parent valide
SELECT meta->>'parent' as code_id, COUNT(*) as nb
FROM documents
WHERE source = 'LEGI' 
  AND doctype = 'section'
  AND meta->>'parent' IN (
      SELECT DISTINCT meta->>'id' FROM documents
      WHERE source = 'LEGI' AND doctype = 'texte'
        AND meta->>'etat' IN ('VIGUEUR', 'ABROGE')
  )
GROUP BY meta->>'parent'
```

### Phase 2 : Récupération métadonnées (v2.2)

```sql
-- Filtre sur état VIGUEUR ou ABROGE uniquement
WHERE meta->>'etat' IN ('VIGUEUR', 'ABROGE')
```

### Intégration
Appelé automatiquement par `daily_pipeline.py` après l'ingestion PostgreSQL.

### Versions
- **v1** (25 jan) : Boucle sur chaque texte (47 jours total)
- **v2.0** (26 jan) : GROUP BY (19s)
- **v2.1** (27 jan) : Fix extraction ID (articles path, sections meta)
- **v2.2** (27 jan) : Filtre codes MODIFIE (77+31 exact)
- **v2.3** (27 jan) : Filtre orphelins Phase 1 (titres génériques exclus)

---

## `legi_cli.py` ⭐ v3.1 (27 jan 2026)

### Rôle
Interface CLI pour interroger PostgreSQL avec cache arborescence depth=10.

### Localisation
`/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`

### Commandes

#### `list_codes`
```bash
legi_cli.py list_codes --scope=<codes_en_vigueur|codes_abroges|all>
```
Liste des codes avec métadonnées (utilise table `code_stats`).

#### `get_code`
```bash
legi_cli.py get_code \
  --code_id=<LEGITEXT...> \
  --depth=<1-10> \
  [--include_articles] \
  [--root_section_id=<LEGISCTA...>] \
  [--page=<N>] \
  [--per_page=<N>] \
  [--date=YYYY-MM-DD] \
  [--no-cache]
```

**Fonctionnalités v3.0** :
- **Cache automatique** : Utilise table `code_trees` (depth=10 pré-calculé)
- **Fonction `_truncate_tree()`** : Tronque depth=10 vers depth demandé
- **Paramètre `--use_cache`** : Défaut True, `--no-cache` pour forcer calcul
- **Performance** : <0.5s avec cache (vs 7-15s sans)

**Correctifs v3.1 (27 jan 2026)** :
- **Bug #1** : Articles jamais retournés (condition après return) ✅
- **Bug #2** : Un seul article retourné (DISTINCT ON num) ✅
- **Bug #3** : 46 articles au lieu de 20 (pas de filtre VIGUEUR) ✅
- **Bug #4** : Doublons dans article_ids (pas de déduplication Python) ✅
- **Bug #5** : Mauvaise version section (tri par date_debut NULL) ✅
- **Bug #6** : Doublons finaux SQL (pas de DISTINCT ON id) ✅

**Comportement v3.1** :
- Par défaut, filtre sur `etat='VIGUEUR'` (articles actuellement applicables)
- Si `--date` fournie, filtre sur période de validité historique
- Déduplication automatique (Python + SQL)
- Tri par `updated_at DESC` pour cohérence

#### `get_articles`
```bash
legi_cli.py get_articles \
  --ids=<id1,id2,...> \
  [--date=YYYY-MM-DD] \
  [--include_links] \
  [--include_breadcrumb]
```

Contenu détaillé d'articles avec liens et breadcrumb.

### Format sortie
JSON sur stdout (parsé par le tool MCP `legifrance_legi`).

### Performances v3.1

| Opération | Sans cache | Avec cache | Gain |
|-----------|------------|------------|------|
| `list_codes` | 0.44s | 0.44s | - |
| `get_code depth=1` | 7.6s | **0.4s** | **18x** |
| `get_code depth=3` | 15s | **0.8s** | **18x** |
| `get_code depth=10` | 90s | **1.5s** | **60x** |
| `get_articles` | 5s | 5s | - |

### Versions
- **v1.0** (25 jan) : Requêtes directes (doublons)
- **v1.1** (26 jan) : Déduplication + pagination
- **v2.0** (26 jan) : Utilise STRUCTURE_TA (sous_sections + articles)
- **v3.0** (26 jan) : Cache depth=10 automatique
- **v3.1** (27 jan) : 6 bugs corrigés (articles, doublons, filtres)

---

## `precalculate_all_trees.py` ⭐ v2 (26 jan 2026)

### Rôle
Pré-calcul des arborescences complètes depth=10 pour tous les codes LEGI.

### Localisation
`/root/legifrance/scripts/precalculate_all_trees.py`

### Fonctionnalités
- Génère arbres depth=10 avec articles pour tous les codes (~171 codes)
- **Batch loading** (v2) : Charge toutes sections en 2-3 requêtes au lieu de récursif SQL
- Sauvegarde dans table `code_trees`
- Monitoring temps génération et tailles
- Skip codes déjà en cache (<24h)
- Gestion erreurs avec retry

### Commandes
```bash
precalculate_all_trees.py [--limit N] [--code-id LEGITEXT...] [--force]
```

**Options** :
- `--limit N` : Limiter à N codes (pour tests)
- `--code-id LEGITEXT` : Générer uniquement ce code
- `--force` : Régénérer même si déjà en cache

### Table cache
```sql
CREATE TABLE code_trees (
    code_id TEXT PRIMARY KEY,
    titre TEXT,
    tree JSONB,  -- Arbre complet depth=10 avec articles
    nb_sections INTEGER,
    nb_articles INTEGER,
    generated_at TIMESTAMP,
    updated_at TIMESTAMP,
    generation_duration_ms INTEGER,
    tree_size_bytes INTEGER
);
```

### Performance
- **1.37s/code** (moyenne)
- **Génération complète** : 3.8 minutes pour 171 codes
- **Taille cache totale** : 115 MB

### Intégration
- Lancement initial : `python3 precalculate_all_trees.py`
- Maintenance : `regenerate_stale_caches.py` (cron quotidien)

### Versions
- **v1** (26 jan) : Récursion SQL naïve (36+ min/code, abandonné)
- **v2** (26 jan) : Batch loading + construction mémoire (1.37s/code)

---

## `regenerate_stale_caches.py` (26 jan 2026)

### Rôle
Maintenance automatique du cache arborescence.

### Fonctionnalités
- Détecte codes avec cache obsolète (`updated_at < NOW() - 24h`)
- Régénère uniquement ceux-là
- Options : `--force`, `--limit`, `--verbose`
- Durée attendue : 5-15 min/jour (selon nb codes modifiés)

### Triggers automatiques
Deux triggers PostgreSQL invalident automatiquement le cache :
- `trigger_invalidate_cache_section` : Sur UPDATE/INSERT sections
- `trigger_invalidate_cache_article` : Sur UPDATE/INSERT articles

### Commandes
```bash
regenerate_stale_caches.py [--force] [--limit N] [--verbose]
```

### Table monitoring
```sql
CREATE TABLE cache_invalidations (
    id SERIAL PRIMARY KEY,
    code_id TEXT,
    reason TEXT,  -- 'section_modified', 'article_modified'
    triggered_at TIMESTAMP,
    document_id TEXT
);
```

### Intégration
Appelé automatiquement par `daily_pipeline.py` (Step 5) après `compute_code_stats`.

---

## `daily_pipeline.py` v2.0 (26 jan 2026)

### Rôle
Exécute les étapes quotidiennes (download, integrity, ingest, compute stats, regen cache) + sanity.

### Étapes
1. `download_archives.py --incremental`
2. `check_integrity.py --auto-fix --relaunch-download`
3. `ingest_legifrance_pg.py --daily --sources LEGI,JORF`
4. `compute_code_stats_v2.py`
5. 🆕 `regenerate_stale_caches.py` (v2.0)
6. Sanity check (inodes + state file)

### Planification
systemd timer à 04:00 Europe/Paris.

### Logs
`/root/legifrance/logs/pipeline_*.log`

### Lock
`/tmp/legifrance_pipeline.lock`

### Exit codes
- 0: OK
- 2: verrou déjà présent
- 3: échec download
- 4: échec integrity
- 5: échec ingest
- 6: échec compute_stats (non-fatal)
- 7: échec regenerate_cache (non-fatal)
- 8: échec sanity

### Durée totale
~1h40-1h50 (quotidien)

---

## Scripts obsolètes (archivés, non utilisés en production)

### `compute_code_stats.py` (v1)
⚠️ Remplacé par `compute_code_stats_v2.py` (Stratégie B)  
Raison : 47 jours vs 19 secondes

### `extract_current.py`
⚠️ Script d'extraction "current" abandonné (saturation inodes).  
Remplacé par `ingest_legifrance_pg.py` (PostgreSQL).

### `extract_dataset.py`
⚠️ Script d'extraction historique (dossiers datés).  
Ne pas utiliser en production : saturation inodes.

---

## 📊 Récapitulatif scripts actifs

| Script | Version | Dernière MAJ | Fonction |
|--------|---------|--------------|----------|
| `download_archives.py` | v1.0 | 25 jan | Téléchargement DILA |
| `check_integrity.py` | v1.0 | 25 jan | Vérification intégrité |
| `ingest_legifrance_pg.py` | **v3.1** | 27 jan | Ingestion PostgreSQL |
| `compute_code_stats_v2.py` | **v2.3** | 27 jan | Stats codes |
| `legi_cli.py` | **v3.1** | 27 jan | CLI + cache |
| `precalculate_all_trees.py` | v2.0 | 26 jan | Pré-calcul cache |
| `regenerate_stale_caches.py` | v1.0 | 26 jan | Maintenance cache |
| `daily_pipeline.py` | v2.0 | 26 jan | Orchestrateur |

**Total scripts actifs** : 8  
**Scripts obsolètes archivés** : 3

---

## 🎯 Bugs corrigés (27 jan 2026)

### `ingest_legifrance_pg.py` v3.1
- ✅ Bug doublons massifs (clé primaire hash path avec timestamp)
- Résultat : 3.9M → 2.5M docs, 0 doublons

### `compute_code_stats_v2.py` v2.1-2.3
- ✅ Bug 3 codes manquants (extraction ID depuis path vs meta)
- ✅ Bug codes MODIFIE comptés ABROGE (CASE statement)
- ✅ Bug codes orphelins titres génériques (filtrage Phase 1)
- Résultat : 74→77 VIGUEUR, 34→31 ABROGE, 0 titres génériques

### `legi_cli.py` v3.1
- ✅ 6 bugs articles/doublons/filtres corrigés
- Résultat : 20 articles uniques (vs 32 avec doublons)

**Dernière mise à jour** : 27 Janvier 2026 17:05 UTC
