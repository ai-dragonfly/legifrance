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

---

## `ingest_legifrance_pg.py` ⭐ v3.0 (Phase 2/3)
### Rôle
Ingestion streaming des archives vers PostgreSQL avec hiérarchie complète.

### Fonctionnalités
- Lecture streaming tar.gz (évite extraction filesystem)
- Parsing XML avec lxml (extraction métadonnées structurées)
- Upsert dans table `documents` (INSERT ON CONFLICT)
- **DELETE optimisé** : Extraction ID regex + DELETE par batch sur `meta->>'id'` (Gain 100x)
- **STRUCTURE_TA** : Extraction sous-sections et articles

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

### Structure métadonnées extraites (v3.0)

#### **TEXTE_VERSION** (codes/TNC)
- `id`, `titre`, `nature`, `etat`, `date_debut`, `date_fin`

#### **SECTION_TA** (sections) - v3.0
- `id`, `titre`, `parent`, `nb_sections`, `nb_articles`
- **`sous_sections`** : Array JSONB avec IDs sous-sections (STRUCTURE_TA)
- **`articles`** : Array JSONB avec IDs articles (STRUCTURE_TA)

#### **ARTICLE** (articles)
- `id`, `num`, `origine`, `date_debut`, `date_fin`, `has_links`, `link_types`

### Performance
- **58 secondes/archive** (moyenne)
- **520 docs/seconde** (freemium)
- **DELETE** : 100x plus rapide (extraction regex ID)

---

## `compute_code_stats_v2.py` ⭐ (Stratégie B)
### Rôle
Pré-calcul statistiques codes pour accélération CLI.

### Fonctionnalités
- Utilise une **Stratégie GROUP BY globale** (au lieu de boucler sur chaque texte)
- Calcule nombre d'articles et sections pour tous les codes
- Upsert dans table `code_stats`

### Sorties
- Table `code_stats` mise à jour (~289K textes)
- Logs : stdout

### Commandes
- `--verbose` : affiche progression détaillée

### Durée
- **~19 secondes** pour toute la base (Gain 8,500x vs v1)
- Doit être lancé après chaque ingestion

### Intégration
Appelé automatiquement par `daily_pipeline.py` après l'ingestion PostgreSQL.

---

## `legi_cli.py` ⭐ v3.1 (Bugs fixes - 27 Jan 2026)
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

#### `get_code` (v3.0 - Cache, v3.1 - Bugs fixes)
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

**Nouveautés v3.0** :
- **Cache automatique** : Utilise table `code_trees` (depth=10 pré-calculé)
- **Fonction `_truncate_tree()`** : Tronque depth=10 vers depth demandé
- **Paramètre `--use_cache`** : Défaut True, `--no-cache` pour forcer calcul
- **Performance** : <0.5s avec cache (vs 7-15s sans)

**Correctifs v3.1 (27 Jan 2026)** :
- **Bug #1** : Articles jamais retournés (condition après return)
- **Bug #2** : Un seul article retourné (DISTINCT ON num)
- **Bug #3** : 46 articles au lieu de 20 (pas de filtre VIGUEUR)
- **Bug #4** : Doublons dans article_ids (pas de déduplication Python)
- **Bug #5** : Mauvaise version section (tri par date_debut NULL)
- **Bug #6** : Doublons finaux SQL (pas de DISTINCT ON id)

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
- **v1.0** : Requêtes directes (doublons)
- **v1.1** : Déduplication + pagination
- **v2.0** : Utilise STRUCTURE_TA (sous_sections + articles)
- **v3.0** : Cache depth=10 automatique
- **v3.1** : ✅ Bugs fixes (6 bugs corrigés)

### Bugs corrigés v3.1

| Bug | Impact | Solution |
|-----|--------|----------|
| Articles jamais retournés | 0% données | Déplacer inclusion articles |
| Un seul article | 97% perte | Supprimer DISTINCT ON num |
| 46 articles (versions historiques) | Versions obsolètes | Filtrer VIGUEUR |
| Doublons article_ids | Pollution | Déduplication Python |
| Mauvaise version section | Incohérence | Tri updated_at |
| Doublons finaux SQL | 13x même ID | DISTINCT ON id |

---

## `precalculate_all_trees.py` ⭐ NOUVEAU (Phase 4b)
### Rôle
Pré-calcul des arborescences complètes depth=10 pour tous les codes LEGI.

### Localisation
`/root/legifrance/scripts/precalculate_all_trees.py`

### Fonctionnalités
- Génère arbres depth=10 avec articles pour tous les codes (~170 codes)
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
    generation_duration_ms INTEGER,
    tree_size_bytes INTEGER
);
```

### Performance
- **19 secondes/code** (moyenne petits codes)
- **60-90 secondes** (codes complexes : Code du travail)
- **Génération complète** : ~60-120 minutes (170 codes)
- **Taille cache totale** : ~500 MB

### Intégration
- Lancement initial : `python3 precalculate_all_trees.py`
- Maintenance : `regenerate_stale_caches.py` (cron quotidien)

---

## `daily_pipeline.py`
### Rôle
Exécute les étapes quotidiennes (download, integrity, ingest, compute stats) + sanity.

### Étapes
1. `download_archives.py --incremental`
2. `check_integrity.py --auto-fix --relaunch-download`
3. `ingest_legifrance_pg.py --daily --sources LEGI,JORF`
4. `compute_code_stats_v2.py`
5. Sanity check (inodes + state file)

### Planification
systemd timer à 04:00 Europe/Paris.

### Logs
`/root/legifrance/logs/pipeline_*.log`

### Exit codes
- 0: OK
- 2: verrou déjà présent
- 3: échec download
- 4: échec integrity
- 5: échec ingest
- 6: échec compute_stats (non-fatal)
- 7: échec sanity

---

## Scripts obsolètes (non utilisés en production)

### `compute_code_stats.py` (v1)
⚠️ Remplacé par `compute_code_stats_v2.py` (Stratégie B)

### `extract_current.py`
⚠️ Script d'extraction "current" abandonné (saturation inodes).  
Remplacé par `ingest_legifrance_pg.py` (PostgreSQL).

### `extract_dataset.py`
⚠️ Script d'extraction historique (dossiers datés).  
Ne pas utiliser en production : saturation inodes.

---

## 📊 **Récapitulatif scripts actifs**

| Script | Version | Fonction | Fréquence |
|--------|---------|----------|-----------|
| `download_archives.py` | v1 | Téléchargement DILA | Quotidien |
| `check_integrity.py` | v1 | Vérification intégrité | Quotidien |
| `ingest_legifrance_pg.py` | **v3.0** | Ingestion PostgreSQL | Quotidien |
| `compute_code_stats_v2.py` | v2 | Stats codes | Quotidien |
| `legi_cli.py` | **v3.1** | CLI avec cache + bugs fixes | À la demande |
| `precalculate_all_trees.py` | v1 | Pré-calcul cache | Initial + cron |
| `daily_pipeline.py` | v1 | Orchestrateur | Quotidien (04:00) |

**Total scripts actifs** : 7  
**Scripts obsolètes** : 3 (archivés)

**Dernière mise à jour** : 27 Janvier 2026
