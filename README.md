# Legifrance Indexing Scripts

Scripts Python standalone pour indexer et rechercher dans les archives XML Légifrance.

## Structure

```
docs/Legifrance/
├── archives/          # Archives tar.gz (JORF, JADE, LEGI, etc.)
├── sqlite3/           # Bases de données (index_*.db)
├── lib/               # Modules réutilisables
│   ├── xml_parser.py
│   ├── archive_scanner.py
│   └── db_manager.py
├── scripts/           # Scripts standalone
│   ├── index_archives.py
│   ├── search_index.py
│   └── extract_xml.py
└── tests/             # Tests unitaires
```

## Quickstart

### 1. Indexer des archives
```bash
cd docs/Legifrance/scripts

python index_archives.py \
  --index-name jorf_test \
  --archives-root ../archives \
  --verbose
```

### 2. Rechercher
```bash
python search_index.py \
  --index-name jorf_test \
  --query "contrat de travail" \
  --limit 10
```

### 3. Extraire un XML
```bash
python extract_xml.py \
  --archive-path ../archives/JORF_20250714.tar.gz \
  --xml-path juri/JORF/TEXT/2025/01/14/JORFTEXT000051234567.xml \
  --output json
```

## Scripts disponibles

| Script | Description |
|--------|-------------|
| `index_archives.py` | Indexation initiale (créer DB) |
| `search_index.py` | Recherche FTS5 + fs_requests |
| `extract_xml.py` | Extraire XML depuis archive |

## Modules lib/

| Module | Description |
|--------|-------------|
| `xml_parser.py` | Parse XML Légifrance (metadata + content) |
| `archive_scanner.py` | Stream tar.gz sans extraction disque |
| `db_manager.py` | Wrapper SQLite + schéma |

## Format archives

```
archives/
  JORF/
    Freemium_jorf_global_20250713-140000.tar.gz
    JORF_20250714-010000.tar.gz
    JORF_20250715-010000.tar.gz
```

Contenu archive :
```
juri/JORF/TEXT/2025/01/14/
  JORFTEXT000051234567.xml
  JORFTEXT000051234568.xml
```

## Schema DB

Tables principales :
- `documents` : métadonnées (xml_id, nature, juridiction, etc.)
- `pages` : contenu texte (1 XML = 1 page)
- `content_fts` : index FTS5 pour recherche

## Développement

Voir `docs/refactoring/` pour la conception complète et le plan d'implémentation.

### Tests
```bash
cd tests
python -m pytest test_xml_parser.py -v
```

### Ajout d'un script
1. Créer `scripts/new_script.py`
2. Importer depuis `lib/`
3. Utiliser `DBManager` pour accès DB
4. Output JSON sur stdout
5. Exit code 0/1/2

## Documentation complète

- [Architecture](../refactoring/01-ARCHITECTURE.md)
- [Modules](../refactoring/02-MODULES.md)
- [Scripts](../refactoring/03-SCRIPTS.md)
- [Plan implémentation](../refactoring/04-IMPLEMENTATION_PLAN.md)
- [Tests](../refactoring/06-TESTING.md)
- [Troubleshooting](../refactoring/07-TROUBLESHOOTING.md)
