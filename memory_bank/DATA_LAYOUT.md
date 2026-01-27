# DATA_LAYOUT — Organisation des données

## Principes
- Les archives `.tar.gz` sont conservées (source de vérité)
- Le dataset est dans **PostgreSQL** (table `documents`)
- Pas d'extraction filesystem (évite saturation inodes)

## Chemins (serveur)

### Archives
- Base : `/mnt/data/legifrance/archives/`
- Par source :
  - `/mnt/data/legifrance/archives/LEGI/freemium/`
  - `/mnt/data/legifrance/archives/LEGI/incremental/`
  - `/mnt/data/legifrance/archives/JORF/freemium/`
  - `/mnt/data/legifrance/archives/JORF/incremental/`
  - Autres sources : CASS, INCA, CAPP, JADE, CONSTIT, CNIL, KALI

### Base de données PostgreSQL
- DB : `legifrance`
- User : `legifrance_app`
- Data directory : `/var/lib/postgresql/14/main` (peut être déplacé sur `/mnt/data` si besoin)
- Schéma :
```sql
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    doctype TEXT NOT NULL,
    path TEXT,
    updated_at TEXT,
    sha256 TEXT,
    meta JSONB,
    content_xml TEXT,
    content_text TEXT
);

-- Index
CREATE INDEX idx_source_doctype ON documents(source, doctype);
CREATE INDEX idx_meta ON documents USING GIN(meta);
CREATE INDEX idx_fts ON documents USING GIN(to_tsvector('french', coalesce(content_text,'')));
```

### Logs
- `/mnt/data/legifrance/logs/`
  - `ingest_pg_YYYYMMDD-HHMMSS.log` : ingestion PostgreSQL
  - `download_YYYYMMDD-HHMMSS.log` : téléchargement
  - `integrity_YYYYMMDD-HHMMSS.log` : vérification intégrité

### Config / state
- `/mnt/data/legifrance/config/`
  - `download_state.json` : état téléchargement
  - `ingest_state.json` : état ingestion PostgreSQL
  - `integrity_report_*.json` : rapports intégrité

### CLI Légifrance
- `/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`

## Symlinks (compat)
Pour stabiliser les chemins :
- `/root/legifrance/archives -> /mnt/data/legifrance/archives`
- `/root/legifrance/logs -> /mnt/data/legifrance/logs`
- `/root/legifrance/config -> /mnt/data/legifrance/config`

## Anti-patterns (INTERDIT)

### Extraction filesystem historique
- `/mnt/data/legifrance/data/` : extraction "par archive/date"
  - Avantage : historisation
  - **Inconvénient : explosion inodes (100% atteint), saturation disque**

**Règle** : ne jamais alimenter en prod. Utiliser PostgreSQL.

### Extraction "current"
- `/mnt/data/legifrance/current/` : état courant par source
  - Même problème : les archives contiennent des chemins datés internes
  - Résultat : millions de fichiers, saturation inodes

**Règle** : abandonné au profit de l'ingestion PostgreSQL.

## Conseils performance
- Ingestion PostgreSQL : streaming tar.gz, pas d'extraction disque
- Mesurer avec `df -h` et `df -i`
- Requêtes PostgreSQL : utiliser les index JSONB et FTS
