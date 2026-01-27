



# PIPELINE_DAILY — Mise à jour quotidienne (04:00 Paris)

## Objectif
Chaque jour à 04:00 heure de Paris (Europe/Paris) :
1. Téléchargement incrémental
2. Vérification d'intégrité des archives (auto-fix)
3. **Ingestion PostgreSQL** (LEGI + JORF)
4. Sanity check (DB counts + state)

## Orchestration
- systemd timer (plutôt que cron)
- Timezone : Europe/Paris
- Orchestrateur : `daily_pipeline.py`
- User : `legifrance_app`

## Locks (anti-doublon)
- `/tmp/legifrance_pipeline.lock` (orchestrateur)
- `/tmp/legifrance_download.lock` (download relancé)
- `/tmp/legifrance_integrity.lock` (check_integrity)
- `/tmp/legifrance_ingest.lock` (ingestion PostgreSQL)

## Scripts impliqués
- `/root/legifrance/scripts/daily_pipeline.py`
- `/root/legifrance/scripts/download_archives.py`
- `/root/legifrance/scripts/check_integrity.py`
- `/root/legifrance/scripts/ingest_legifrance_pg.py`

## Commandes (manuel)

### Init one-shot (avant le quotidien)
```bash
# Téléchargement complet
python3 /root/legifrance/scripts/download_archives.py --all

# Ingestion initiale (LEGI + JORF)
sudo -u legifrance_app python3 /root/legifrance/scripts/ingest_legifrance_pg.py --init --sources LEGI,JORF
```

### Run quotidien (manuel)
```bash
sudo -u legifrance_app python3 /root/legifrance/scripts/daily_pipeline.py
```

### Run en tâche de fond
```bash
sudo -u legifrance_app nohup python3 /root/legifrance/scripts/daily_pipeline.py \
  > /tmp/pipeline_manual.log 2>&1 </dev/null &
```

## Monitoring

### Logs pipeline
```bash
ls -lt /root/legifrance/logs | head

# Logs ingestion PostgreSQL
tail -200 /root/legifrance/logs/ingest_pg_*.log

# Logs téléchargement
tail -200 /root/legifrance/logs/download_*.log
```

### État PostgreSQL
```bash
# Nombre de documents
sudo -u legifrance_app psql -d legifrance -c "SELECT source, doctype, COUNT(*) FROM documents GROUP BY source, doctype;"

# Taille DB
sudo -u legifrance_app psql -d legifrance -c "SELECT pg_size_pretty(pg_database_size('legifrance'));"
```

### Report JSON
```bash
ls -lt /root/legifrance/config/pipeline_report_*.json | head
```

### Stockage (priorité INODES)
```bash
df -i /mnt/data

df -h /mnt/data
```

## Notes importantes
- Si les inodes approchent 95%+, interrompre et nettoyer (voir OPS_RUNBOOK.md).
- L'extraction HISTORIQUE (dossiers datés) est **interdite** en prod.
- L'extraction CURRENT est **abandonnée** au profit de l'ingestion PostgreSQL.

 
 
 
 
