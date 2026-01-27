# OPS_RUNBOOK — Exploitation & incidents

## 1) Incident : `No space left on device` alors qu'il reste de l'espace
### Cause fréquente
- INODES à 100% (trop de fichiers)

### Diagnostic
```bash
df -h /mnt/data
df -i /mnt/data
```

### Remédiation (cas historique)
Si l'historique a rempli les inodes (extraction datée) :
- supprimer `/mnt/data/legifrance/data/*`
- supprimer `/mnt/data/legifrance/current/*`
- garder archives `.tar.gz`

⚠️ Opération lourde (millions de fichiers) : `rm -rf` prend du temps.

### Vérifier la progression d'un nettoyage
```bash
ps aux | grep "rm -rf /mnt/data/legifrance" | grep -v grep

df -i /mnt/data
```

---

## 2) Download corrompu / incomplet
### Symptômes
- `gzip -t` échoue
- erreurs `.part` / rename

### Remédiation
- S'assurer qu'un seul downloader tourne
- Supprimer `.part` orphelins
- Lancer `check_integrity.py --auto-fix --relaunch-download`

---

## 3) Doublon de jobs (deux scripts en parallèle)
### Symptômes
- erreurs `.part` (rename impossible)
- collisions de fichiers

### Remédiation
- tuer les doublons : `pkill -f download_archives.py`
- nettoyer `.part`
- relancer une seule instance via nohup

---

## 4) Locks bloqués
### Symptômes
- un script refuse de démarrer (lock exists)

### Remédiation
- vérifier si un process existe vraiment
- si non : supprimer le lock
```bash
# Locks possibles
ls -l /tmp/legifrance_*.lock

# Supprimer si processus mort
rm -f /tmp/legifrance_ingest.lock
```

---

## 5) Ingestion PostgreSQL bloquée
### Symptômes
- processus en cours mais aucun progrès
- logs figés

### Diagnostic
```bash
# Processus actif ?
ps aux | grep ingest_legifrance_pg

# Connexions PostgreSQL
sudo -u legifrance_app psql -d legifrance -c "SELECT * FROM pg_stat_activity WHERE datname='legifrance';"

# Locks PostgreSQL
sudo -u legifrance_app psql -d legifrance -c "SELECT * FROM pg_locks WHERE database = (SELECT oid FROM pg_database WHERE datname='legifrance');"
```

### Remédiation
- Tuer le processus d'ingestion : `pkill -9 -f ingest_legifrance_pg.py`
- Supprimer lock : `rm -f /tmp/legifrance_ingest.lock`
- Vérifier l'intégrité DB :
```bash
sudo -u legifrance_app psql -d legifrance -c "SELECT COUNT(*) FROM documents;"
```
- Relancer ingestion

---

## 6) PostgreSQL hors service
### Symptômes
- Erreur connexion : `could not connect to server`

### Diagnostic
```bash
systemctl status postgresql@14-main.service
```

### Remédiation
```bash
sudo systemctl restart postgresql@14-main.service
```

---

## 7) Monitoring quotidien minimal
```bash
# logs
ls -lt /root/legifrance/logs | head

# inodes & espace
df -i /mnt/data
df -h /mnt/data

# PostgreSQL
sudo -u legifrance_app psql -d legifrance -c "SELECT source, doctype, COUNT(*) FROM documents GROUP BY source, doctype;"
sudo -u legifrance_app psql -d legifrance -c "SELECT pg_size_pretty(pg_database_size('legifrance'));"
```
