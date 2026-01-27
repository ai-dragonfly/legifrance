# ARCHITECTURE — Système Légifrance (vue d'ensemble)

## Objectif
Maintenir automatiquement (quotidiennement) un **dataset PostgreSQL** des archives Légifrance (DILA OPENDATA), avec une chaîne robuste :

1. Téléchargement incrémental (DILA OPENDATA)
2. Vérification d'intégrité (manquants + corruption)
3. **Ingestion dans PostgreSQL** (parsing XML + upsert)
4. **Pré-calcul cache arborescence** (depth=10 complet)
5. Vérification post-ingestion (sanity checks)

Le tout est piloté depuis notre environnement local via le serveur MCP et le tool `ssh_client`.

## Perspective (notre système distribué)

### Côté local (repo Git)
- Code du serveur MCP (FastAPI)
- Tools MCP : 
  - `ssh_client` : exécution distante, upload/download
  - `legifrance_legi` : interrogation codes LEGI via CLI distant
- Dossier miroir serveur : `server_legifrance/` (source de vérité)
  - scripts : `server_legifrance/mirror/root/legifrance/scripts/`
  - CLI : `server_legifrance/mirror/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`
  - memory bank : `server_legifrance/memory_bank/`
  - deploy : `server_legifrance/deploy/`

### Côté serveur (Hetzner)
- Ubuntu 22.04
- Volume data monté sur `/mnt/data`
- PostgreSQL 14 (peer auth)
- User système : `legifrance_app` (owner data + accès DB)
- Dossier de travail : `/root/legifrance` (avec symlinks vers `/mnt/data/legifrance/*`)
- CLI Légifrance : `/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`

## Composants

### Scripts (serveur)
- `download_archives.py` : téléchargement archives DILA (freemium + incremental)
- `check_integrity.py` : vérification archives (listing distant + `gzip -t`)
- `ingest_legifrance_pg.py` : **ingestion PostgreSQL** (streaming tar.gz, parsing XML, upsert)
- `compute_code_stats_v2.py` : **pré-calcul statistiques** codes (table `code_stats`)
- `precalculate_all_trees.py` : **pré-calcul arbres depth=10** (table `code_trees`)
- `legi_cli.py` : **interface CLI** pour interroger PostgreSQL (tool MCP)
- `daily_pipeline.py` : orchestrateur quotidien (download → check → ingest → compute stats)

### Base de données (PostgreSQL)
- DB : `legifrance`
- User : `legifrance_app` (peer auth)
- Tables :
  - **`documents`** : table principale (3.9M+ documents LEGI)
    - Colonnes : `id`, `source`, `doctype`, `path`, `updated_at`, `sha256`, `meta` (JSONB), `content_xml`, `content_text`
    - Index : btree sur `(source, doctype)`, GIN sur `meta`, GIN FTS sur `content_text`, B-tree sur `path`
  - **`code_stats`** : table pré-calculée pour accélération CLI
    - Colonnes : `code_id`, `titre`, `nature`, `etat`, `nb_articles`, `nb_sections`, `updated_at`
    - Index : B-tree sur `etat`
  - **`code_trees`** : table cache arborescences depth=10 (Phase 4)
    - Colonnes : `code_id`, `titre`, `tree` (JSONB), `nb_sections`, `nb_articles`, `generated_at`, `generation_duration_ms`, `tree_size_bytes`
    - Index : B-tree sur `updated_at`
  - **`cache_invalidations`** : monitoring invalidations cache
    - Colonnes : `id`, `code_id`, `reason`, `triggered_at`, `document_id`

### CLI Légifrance
- Path : `/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`
- Commandes :
  - `list_codes` : liste codes en vigueur/abrogés (0.44s)
  - `get_code` : arborescence code (récursif, depth 1-10, **avec cache <0.5s**)
  - `get_articles` : contenu articles avec liens et breadcrumb (5s)
- Appelé par le tool MCP `legifrance_legi` via SSH

### Outils MCP (local)
- `ssh_client` : exécution distante, upload/download, orchestration par l'IA
- `legifrance_legi` : exposer `list_codes`, `get_code`, `get_articles` au LLM

## Flux d'exécution

### Init (one-shot)
- téléchargement complet (freemium + incremental existants)
- integrity check global
- ingestion PostgreSQL `--init --sources LEGI,JORF`
- compute code stats initial
- **pré-calcul cache depth=10** (170 codes, ~90 min)

### Quotidien (04:00 Europe/Paris via systemd)
- `download_archives.py --incremental`
- `check_integrity.py --auto-fix --relaunch-download`
- `ingest_legifrance_pg.py --daily --sources LEGI,JORF`
- `compute_code_stats_v2.py` (pré-calcul pour CLI)
- **régénération cache** (codes modifiés seulement, ~5-15 min)
- sanity check (counts DB)

## Règles critiques
- Priorité = INODES : `df -i /mnt/data`
- **NE JAMAIS** extraire l'historique sur filesystem (dossiers datés) : saturation inodes
- Tous les scripts longs doivent : lockfile + statefile + logs
- Ingestion PostgreSQL : streaming tar.gz **sans extraction disque**

## Optimisations

### **Table `code_stats`** 
- Pré-calcul stats codes pour `list_codes` (0.44s vs timeout)

### **Table `code_trees`** (Phase 4)
- Cache arborescences depth=10 complètes (~170 codes)
- Performance : **<0.5s** (vs 7-15s sans cache)
- Taille totale : ~500 MB
- Régénération : quotidienne (codes modifiés seulement)

### **Index GIN JSONB**
- `meta->>'parent'` pour traversée hiérarchique rapide

### **Index path**
- `idx_documents_path_pattern` pour requêtes LIKE (si besoin)

### **Colonne `parent`**
- Extraction depuis `CONTEXTE/TEXTE` (XML)
- 173,625 sections avec parent (42.4%)

### **Colonnes `sous_sections` et `articles`** (v3.0)
- Extraction depuis `STRUCTURE_TA` (XML)
- 148,712 sections avec sous-sections (36.3%)
- 283,134 sections avec articles (69.1%)
- Permet construction arborescence depth=10 sans requêtes récursives

## Architecture cache (Phase 4)

### **Principe**
Pré-calculer les arbres depth=10 pour tous les codes et les sauvegarder en JSONB.

### **Avantages**
- ✅ Performance : <0.5s (vs 7-15s calcul dynamique)
- ✅ Gain : 18x à 60x selon depth
- ✅ Pas de requêtes récursives à chaque appel
- ✅ Fonction `_truncate_tree()` pour depths partiels

### **Fonctionnement**
```
┌─────────────────┐
│   get_code()    │
│   depth=3       │
└────────┬────────┘
         │
         ↓
    ┌────────────┐     OUI     ┌──────────────────┐
    │ Cache      │───────────→ │ Récupère depth=10│
    │ exists?    │             │ depuis code_trees│
    └────────────┘             └────────┬─────────┘
         │ NON                           │
         ↓                               ↓
    ┌────────────────┐         ┌──────────────────┐
    │ Calcul         │         │ _truncate_tree() │
    │ dynamique      │         │ depth=10 → 3     │
    │ depth=10       │         └────────┬─────────┘
    └────────┬───────┘                  │
             │                          │
             ↓                          ↓
    ┌────────────────┐         ┌──────────────────┐
    │ Sauvegarde     │         │ Retourne JSON    │
    │ dans cache     │         │ (< 0.5s)         │
    └────────────────┘         └──────────────────┘
```

### **Maintenance**
- **Invalidation** : Trigger PostgreSQL sur INSERT/UPDATE documents
- **Régénération** : Cron quotidien 02:00 (codes modifiés seulement)
- **Monitoring** : Table `cache_invalidations` (historique)

## Dépannage rapide
- Voir `OPS_RUNBOOK.md` (inodes, corruption, blocages, locks)
