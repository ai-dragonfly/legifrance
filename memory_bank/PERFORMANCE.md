# PERFORMANCE — Métriques et optimisations

## Métriques CLI (état actuel)

### `list_codes` ⚡
- **Avant optimisation** : Timeout (>60s)
- **Après optimisation** : **0.44s**
- **Méthode** : Table `code_stats` pré-calculée
- **Gain** : **>135x** plus rapide

### `get_code` (v3.0 - Cache)
- **Sans cache** : 7-15s (petits codes), >90s (codes complexes)
- **Avec cache** : **0.4-1.5s** (tous codes)
- **Méthode** : Table `code_trees` depth=10 pré-calculé
- **Gain** : **18x à 60x** selon profondeur

| Depth | Sans cache | Avec cache | Gain |
|-------|------------|------------|------|
| 1 | 7.6s | **0.4s** | **18x** |
| 3 | 15s | **0.8s** | **18x** |
| 5 | 45s | **1.2s** | **37x** |
| 10 | 90s | **1.5s** | **60x** |

### `get_articles`
- **Temps** : **5.02s** (pour 3 articles)
- **Méthode** : Requête `IN (id1, id2, id3)` directe
- **Optimisation** : Index sur `meta->>'id'` (via GIN JSONB)

---

## Métriques ingestion

### Freemium LEGI
- **Fichiers** : 2,557,045 documents XML
- **Taille** : ~1.9 GB compressé
- **Durée** : 82 minutes
- **Throughput** : ~520 docs/sec

### Incrémental quotidien (moyenne)
- **Fichiers** : ~2,500 documents par archive
- **Durée** : 4-8 secondes par archive
- **Throughput** : ~300-600 docs/sec

### Optimisation DELETE (v3.0)
- **Avant** : 41 min/archive (DELETE document par document)
- **Après** : **19 sec/archive** (DELETE par batch + regex ID)
- **Gain** : **100x plus rapide**

---

## Métriques PostgreSQL

### Taille base de données
- **État actuel** : 17 GB
- **LEGI seul** : ~17 GB
- **Avec JORF estimé** : ~25-30 GB

### Index créés
| Index | Type | Taille estimée | Utilisation |
|-------|------|----------------|-------------|
| `documents_pkey` | B-tree | ~200 MB | Lookup par ID |
| `idx_source_doctype` | B-tree | ~50 MB | Filtrage type documents |
| `idx_meta` | GIN JSONB | ~500 MB | Requêtes sur métadonnées |
| `idx_fts` | GIN FTS | ~300 MB | Recherche full-text |
| `idx_documents_path_pattern` | B-tree | ~100 MB | Requêtes LIKE (peu utilisé) |

### Compteurs documents (ingestion complète)
| Type | Nombre | % |
|------|--------|---|
| **Articles** | 3,098,351 | 78.3% |
| **Textes** | 422,953 | 10.7% |
| **Sections** | 409,529 | 10.4% |
| **XML** | 25,113 | 0.6% |
| **TOTAL** | **3,955,946** | 100% |

### Tables cache
| Table | Taille | Rows | Fonction |
|-------|--------|------|----------|
| `code_stats` | ~50 MB | 289K | Stats codes (list_codes) |
| `code_trees` | **~500 MB** | **170** | Arbres depth=10 (get_code) |

---

## Optimisations appliquées

### 1. Table `code_stats` (pré-calcul)
**Problème** : `list_codes` comptait en direct avec `COUNT(*)` sur 2M docs → timeout

**Solution** :
- Table séparée avec stats pré-calculées
- Mise à jour quotidienne par `compute_code_stats_v2.py`
- Requêtes instantanées

**Résultat** : 0.44s (vs timeout)

### 2. Table `code_trees` (pré-calcul depth=10) ⭐ Phase 4
**Problème** : `get_code` calculait l'arbre récursivement → 7-90s selon complexité

**Solution** :
- Pré-calcul arbres depth=10 complets pour tous les codes
- SauvegardB dans table `code_trees`
- Fonction `_truncate_tree()` pour depths partiels
- Régénération quotidienne (codes modifiés seulement)

**Résultat** : 
- 0.4s pour depth=1 (vs 7.6s) = **18x plus rapide**
- 1.5s pour depth=10 (vs 90s) = **60x plus rapide**
- Taille totale : ~500 MB pour 170 codes

### 3. Index GIN sur `meta` (JSONB)
**Problème** : Requêtes sur `meta->>'parent'` lentes

**Solution** :
- Index GIN JSONB sur colonne `meta`
- Supporte requêtes `@>`, `->`, `->>`

**Résultat** : Requêtes hiérarchiques rapides

### 4. Streaming tar.gz (ingestion)
**Problème** : Extraction disque saturait les inodes

**Solution** :
- Lecture streaming directe depuis tar.gz
- Parsing XML en mémoire
- Upsert PostgreSQL sans extraction

**Résultat** : 0 fichiers sur disque, ingestion possible

### 5. DELETE optimisé (v3.0)
**Problème** : Suppression document par document → 41 min/archive

**Solution** :
- Extraction IDs via regex depuis `liste_suppression_*.dat`
- DELETE par batch : `DELETE FROM documents WHERE meta->>'id' = ANY(array_ids)`
- Index GIN sur `meta->>'id'` utilisé

**Résultat** : **19 sec/archive** (100x plus rapide)

### 6. Extraction STRUCTURE_TA (v3.0)
**Problème** : Hiérarchie section→section impossible (0 liens)

**Solution** :
- Parsing `STRUCTURE_TA/LIEN_SECTION_TA` (sous-sections)
- Parsing `STRUCTURE_TA/LIEN_ART` (articles)
- Sauvegarde en JSONB dans `meta`

**Résultat** :
- 148,712 sections avec sous-sections (36.3%)
- 283,134 sections avec articles (69.1%)
- Construction arborescence depth=10 sans requêtes récursives

---

## Benchmarks

### Hardware serveur
- **CPU** : Shared vCPU (Hetzner CPX31)
- **RAM** : 8 GB
- **Disque** : Volume SSD 300 GB
- **OS** : Ubuntu 22.04

### Charges observées

#### Ingestion LEGI (pic)
- **CPU** : 36-50%
- **RAM** : 3.4 GB (PostgreSQL + Python)
- **Disk I/O** : ~50 MB/s write

#### Compute code stats
- **CPU** : 2-5%
- **RAM** : 200 MB
- **Disk I/O** : ~10 MB/s read
- **Durée** : **18.8s** pour 289K textes (Stratégie B)

#### Précalcul cache depth=10
- **CPU** : 10-20%
- **RAM** : 400 MB
- **Disk I/O** : ~20 MB/s read
- **Durée** : **19s/code** (moyenne), **60-90s** (codes complexes)
- **Total** : ~90 min pour 170 codes

#### Requêtes CLI (normal)
- **CPU** : <1%
- **RAM** : 50 MB
- **Disk I/O** : <1 MB/s (avec cache)

---

## Recommandations scaling

### Si charge augmente (JORF + autres sources)
1. **Upgrader RAM** : 16 GB recommandé (PostgreSQL shared_buffers)
2. **Passer en dedicated CPU** : Pour ingestion plus rapide
3. **Séparer compute_code_stats** : Le lancer en off-peak (nuit)
4. **Ajouter read replica** : PostgreSQL streaming replication pour requêtes CLI

### Si volumes augmentent (x10)
1. **Partitionnement** : Par source (LEGI, JORF, CASS, etc.)
2. **Archivage** : Textes abrogés dans table séparée
3. **Compression** : `content_text` et `content_xml` avec TOAST
4. **Cache Redis** : Front de `code_trees` pour codes très consultés

---

## Monitoring recommandé

### Métriques clés à surveiller
- **Disk usage** : `df -h /mnt/data` (seuil 80%)
- **Inodes** : `df -i /mnt/data` (seuil 90%)
- **DB size** : `pg_database_size('legifrance')` (seuil 250 GB)
- **Query slow log** : PostgreSQL `log_min_duration_statement = 1000`
- **Cache hit rate** : `code_trees` utilisation vs calcul dynamique

### Alertes recommandées
- Inodes > 90% → CRITIQUE
- DB size > 250 GB → WARNING
- Ingestion failed → CRITIQUE
- Compute_code_stats > 6h → WARNING
- Cache generation failed → WARNING

---

## Historique optimisations

| Date | Optimisation | Gain mesuré |
|------|--------------|-------------|
| 2026-01-25 | Table `code_stats` | 135x (timeout → 0.44s) |
| 2026-01-26 | DELETE optimisé | 100x (41 min → 19s) |
| 2026-01-26 | compute_stats v2 | 8,500x (47 jours → 19s) |
| 2026-01-26 | STRUCTURE_TA | Hiérarchie complète (0% → 36-69%) |
| 2026-01-26 | **Cache depth=10** | **18-60x** (7-90s → 0.4-1.5s) |
