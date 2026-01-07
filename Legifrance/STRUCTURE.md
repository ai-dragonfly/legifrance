# Structure du projet Legifrance

## Arborescence complète

```
docs/Legifrance/
├── archives/                    # Archives Légifrance (tar.gz)
│   ├── JORF/
│   │   ├── freemium/
│   │   │   └── Freemium_jorf_global_20250713-140000.tar.gz  (1.7 GB)
│   │   └── incremental/         # Vide (archives quotidiennes à venir)
│   ├── JADE/
│   │   ├── freemium/
│   │   │   └── Freemium_jade_global_20250713-140000.tar.gz  (1.2 GB)
│   │   └── incremental/         # 130 archives quotidiennes
│   ├── LEGI/
│   │   ├── freemium/
│   │   │   └── Freemium_legi_global_20250713-140000.tar.gz  (1.1 GB)
│   │   └── incremental/         # 40 archives quotidiennes
│   ├── CASS/                    # Cour de cassation
│   ├── CAPP/                    # Cour d'appel
│   ├── CNIL/                    # CNIL
│   ├── CONSTIT/                 # Conseil constitutionnel
│   ├── INCA/                    # Conventions collectives
│   └── KALI/                    # Conventions collectives nationales
│
├── lib/                         # Modules réutilisables
│   ├── xml_parser.py            # Parse XML Légifrance (3.3 KB)
│   ├── archive_scanner.py       # Stream tar.gz (3.4 KB)
│   └── db_manager.py            # SQLite wrapper (4.3 KB)
│
├── scripts/                     # Scripts standalone
│   ├── index_archives.py        # Indexation initiale (7.0 KB)
│   ├── search_index.py          # Recherche FTS5 (3.9 KB)
│   └── extract_xml.py           # Extraire XML (2.2 KB)
│
├── tests/                       # Tests
│   ├── create_test_archive.py   # Créer archive test (2.4 KB)
│   └── test_basic.py            # Test intégration (3.5 KB)
│
├── sqlite3/                     # Bases de données (créé après indexation)
│   └── index_*.db               # Ex: index_jorf_prod.db
│
├── README.md                    # Guide principal
└── SPRINT1_COMPLETE.md          # Résumé Sprint 1
```

## Volumes de données

### Archives existantes
| Source | Type | Taille | XMLs (estimation) | Status |
|--------|------|--------|-------------------|--------|
| JORF | Freemium | 1.7 GB | ~200k | ✅ Disponible |
| JADE | Freemium | 1.2 GB | ~2M | ✅ Disponible |
| LEGI | Freemium | 1.1 GB | ~500k | ✅ Disponible |
| INCA | Freemium | 687 MB | ~100k | ✅ Disponible |
| CAPP | Freemium | 292 MB | ~50k | ✅ Disponible |
| CASS | Freemium | 260 MB | ~50k | ✅ Disponible |
| KALI | Freemium | 182 MB | ~30k | ✅ Disponible |
| CNIL | Freemium | 18 MB | ~5k | ✅ Disponible |
| CONSTIT | Freemium | 12 MB | ~2k | ✅ Disponible |
| **Total** | **Freemium** | **~5.3 GB** | **~3M XMLs** | ✅ |

### Archives incrémentales
| Source | Archives | Période | Taille moyenne |
|--------|----------|---------|----------------|
| JADE | 130 | Jul-Jan 2026 | 200-800 KB |
| LEGI | 40 | Jul-Aug 2025 | 1-9 MB |
| CNIL | 43 | Jul-Jan 2026 | 2-80 KB |
| INCA | 21 | Jul-Jan 2026 | 10-400 KB |
| CASS | 20 | Jul-Jan 2026 | 10-500 KB |
| CAPP | 13 | Aug-Nov 2025 | 3-18 KB |
| CONSTIT | 9 | Jul-Dec 2025 | 14-765 KB |

## Code source

### Modules (lib/)

**xml_parser.py** (3.3 KB)
- `parse_legifrance_xml()` — Parse XML + extract metadata
- `extract_metadata()` — Extract <META> section
- `extract_content_blocks()` — Concatenate <CONTENU>
- Support: JURI (jurisprudence) + LEGI (codes)

**archive_scanner.py** (3.4 KB)
- `scan_archives()` — Scan directory, sort chronologically
- `stream_archive()` — Stream XMLs from tar.gz
- Memory-efficient: no disk extraction

**db_manager.py** (4.3 KB)
- `DBManager` — SQLite wrapper (context manager)
- `create_legifrance_index()` — Create DB with schema
- Schema: documents, pages, content_fts (FTS5)

### Scripts

**index_archives.py** (7.0 KB)
- Initial indexing (create DB)
- Parse XMLs, insert documents + pages
- FTS5 automatic indexing via triggers
- Output: JSON (operation, status, stats)

**search_index.py** (3.9 KB)
- Search using FTS5
- Output formats: JSON, fs_requests
- Snippets with query context

**extract_xml.py** (2.2 KB)
- Extract XML from tar.gz
- Output formats: XML (raw), JSON (parsed)

### Tests

**create_test_archive.py** (2.4 KB)
- Generate test archives (N XMLs)
- Sample content (contrat de travail, licenciement)

**test_basic.py** (3.5 KB)
- Full workflow test (create → index → search → extract)
- Validates all scripts work end-to-end

## Utilisation

### Indexer une archive Freemium
```bash
cd docs/Legifrance/scripts

python index_archives.py \
  --index-name jade_prod \
  --archives-root ../archives/JADE \
  --verbose
```

### Indexer toutes les sources
```bash
for source in JORF JADE LEGI CASS CAPP CNIL CONSTIT INCA KALI; do
  python index_archives.py \
    --index-name ${source,,}_prod \
    --archives-root ../archives/$source \
    --sources $source \
    --verbose
done
```

### Rechercher
```bash
python search_index.py \
  --index-name jade_prod \
  --query "contrat de travail" \
  --limit 20 \
  --output-format fs-requests
```

### Extraire XML
```bash
python extract_xml.py \
  --archive-path ../archives/JADE/freemium/Freemium_jade_global_20250713-140000.tar.gz \
  --xml-path juri/JADE/TEXT/2025/01/06/JURITEXT000048201.xml \
  --output json
```

## Prochaines étapes (Sprint 2)

### Scripts à créer
- [ ] `reindex_archives.py` — Réindexation incrémentale
- [ ] `stats_index.py` — Statistiques index
- [ ] `list_indexes.py` — Lister tous les index

### Fonctionnalités
- [ ] Delta-skip (archive-level + XML-level)
- [ ] Métriques avancées (natures, juridictions, dates)
- [ ] Support multi-index queries

### Tests
- [ ] Test réindexation (3 archives successives)
- [ ] Test performance (10k XMLs)
- [ ] Benchmark search latency

## Documentation complète

Voir `docs/refactoring/` pour :
- Architecture détaillée
- Plan d'implémentation (6 sprints)
- Tests stratégie
- Troubleshooting
