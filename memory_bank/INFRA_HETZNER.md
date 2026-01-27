# INFRA_HETZNER — Serveur, volume, montage

## Serveur
- Provider : Hetzner Cloud
- OS : Ubuntu 22.04.5 LTS
- Hôte : `legifrance-indexer`
- IP publique : `YOUR_SERVER_IP`

## Stockage

### Disque système
- Device : `/dev/sda1`
- Mount : `/`
- Usage : OS + code + petits artefacts + PostgreSQL data (par défaut)
- Règle : ne jamais extraire le dataset sur `/` (filesystem)

### Volume data
- Device : `/dev/sdb` (300G)
- Filesystem : ext4
- Mount : `/mnt/data`
- Persisté via `/etc/fstab` (UUID)
- Usage : archives `.tar.gz` (source de vérité)

Commande utile :
```bash
lsblk
df -h /mnt/data
df -i /mnt/data  # Priorité : surveiller les inodes
```

## PostgreSQL

### Installation
- Version : PostgreSQL 14
- Cluster : `14/main`
- Port : 5432 (local unix socket)
- Data directory : `/var/lib/postgresql/14/main` (peut être déplacé sur `/mnt/data` si volume croît)

### Configuration
- DB : `legifrance`
- User : `legifrance_app` (role PostgreSQL + user système)
- Auth : peer (connexion locale sans password)

### Commandes utiles
```bash
# Status
systemctl status postgresql@14-main.service

# Se connecter
sudo -u legifrance_app psql -d legifrance

# Taille DB
sudo -u legifrance_app psql -d legifrance -c "SELECT pg_size_pretty(pg_database_size('legifrance'));"

# Nombre de documents
sudo -u legifrance_app psql -d legifrance -c "SELECT COUNT(*) FROM documents;"

# Répartition par source/doctype
sudo -u legifrance_app psql -d legifrance -c "SELECT source, doctype, COUNT(*) FROM documents GROUP BY source, doctype;"
```

## Dossiers serveur (convention)

### Workspace scripts
- `/root/legifrance/scripts/`
  - `download_archives.py`
  - `check_integrity.py`
  - `ingest_legifrance_pg.py`
  - `daily_pipeline.py`

### CLI Légifrance
- `/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`

### Symlinks (compat)
Pour maintenir des chemins stables tout en stockant sur le volume :
- `/root/legifrance/archives -> /mnt/data/legifrance/archives`
- `/root/legifrance/logs -> /mnt/data/legifrance/logs`
- `/root/legifrance/config -> /mnt/data/legifrance/config`

### Données
- Archives : `/mnt/data/legifrance/archives/<SOURCE>/{freemium|incremental}/*.tar.gz`
- PostgreSQL : table `documents` dans DB `legifrance`

⚠️ Dossiers interdits (saturation inodes) :
- `/mnt/data/legifrance/data/` (extraction historique)
- `/mnt/data/legifrance/current/` (extraction current)

## User système

### `legifrance_app`
- UID/GID : 998
- Home : `/var/lib/legifrance`
- Shell : `/bin/bash`
- Propriétaire : `/mnt/data/legifrance/{logs,config}`
- Accès : archives (lecture), PostgreSQL (peer auth)

## Monitoring critique

### Priorité : INODES
Le message `No space left on device` survient souvent par manque d'inodes.

```bash
# INODES (priorité absolue)
df -i /mnt/data

# Espace disque
df -h /mnt/data
```

### PostgreSQL
```bash
# Taille DB
sudo -u legifrance_app psql -d legifrance -c "SELECT pg_size_pretty(pg_database_size('legifrance'));"

# Activité
sudo -u legifrance_app psql -d legifrance -c "SELECT * FROM pg_stat_activity WHERE datname='legifrance';"
```

## Événements notables
- **2026-01-25** : Extraction historique ALL a saturé les inodes (100%) → nettoyage obligatoire. Stratégie changée vers ingestion PostgreSQL.
- **2026-01-25** : Création user système `legifrance_app`, déploiement CLI, ingestion PostgreSQL opérationnelle.

Voir `CHANGELOG_OPERATIONS.md` pour l'historique complet.
