# OPS_PROCEDURES — Procédures opérationnelles

## Ajout colonne `code_id` dénormalisée (à faire après fin ingestion)

### Objectif
Accélérer `get_code` en évitant les requêtes `LIKE '%LEGITEXT%'` qui ne peuvent pas utiliser l'index.

### Procédure

#### 1. Ajouter la colonne
```sql
ALTER TABLE documents ADD COLUMN code_id TEXT;
```

#### 2. Remplir la colonne
```sql
-- Méthode 1 : Extraction depuis path (pour tous les documents)
UPDATE documents 
SET code_id = (regexp_match(path, '(LEGITEXT[0-9]+)'))[1]
WHERE path IS NOT NULL 
  AND path LIKE '%LEGITEXT%';

-- Méthode 2 : Pour les sections et articles, extraire depuis meta->>'parent' (plus fiable)
UPDATE documents 
SET code_id = meta->>'parent'
WHERE source = 'LEGI'
  AND doctype IN ('section', 'article')
  AND meta->>'parent' LIKE 'LEGITEXT%';
```

#### 3. Créer l'index
```sql
CREATE INDEX idx_documents_code_id ON documents(code_id) 
WHERE code_id IS NOT NULL;
```

#### 4. Modifier `legi_cli.py` pour utiliser `code_id`
Remplacer les requêtes :
```python
# AVANT
WHERE path LIKE '%LEGITEXT000005634379%'

# APRÈS
WHERE code_id = 'LEGITEXT000005634379'
```

### Durée estimée
- ALTER TABLE : instantané (ajoute juste métadonnée)
- UPDATE : ~10-30 minutes (2.5M documents)
- CREATE INDEX : ~5-10 minutes

### État actuel
⏳ **Bloqué** : L'ingestion est en cours et maintient un verrou de table. Attendre fin ingestion.

---

## Recalcul `code_stats` après ingestion

### Objectif
Mettre à jour les statistiques codes après chaque ingestion (quotidienne).

### Procédure

#### 1. Vider la table (optionnel, pour recalcul complet)
```sql
TRUNCATE TABLE code_stats;
```

#### 2. Lancer le calcul
```bash
sudo -u legifrance_app python3 /root/legifrance/scripts/compute_code_stats.py
```

#### 3. Vérifier
```sql
SELECT COUNT(*) FROM code_stats;
SELECT COUNT(*) FILTER (WHERE nature ILIKE '%CODE%') as codes FROM code_stats;
```

### Durée estimée
- ~2-3 heures pour 288K textes

### Intégration
✅ Automatisé dans `daily_pipeline.py` (étape 4)

---

## Déblocage requêtes PostgreSQL

### Symptôme
Les requêtes timeout ou bloquent indéfiniment.

### Diagnostic
```sql
-- Voir les requêtes actives
SELECT pid, state, query_start, left(query, 80) 
FROM pg_stat_activity 
WHERE datname = 'legifrance' 
  AND state != 'idle' 
ORDER BY query_start;

-- Voir les verrous
SELECT 
  pg_locks.pid,
  pg_locks.mode,
  pg_locks.granted,
  pg_stat_activity.query
FROM pg_locks
JOIN pg_stat_activity ON pg_locks.pid = pg_stat_activity.pid
WHERE pg_locks.re'documents'::regclass;
```

### Solution
```sql
-- Tuer une requête spécifique (si nécessaire)
SELECT pg_cancel_backend(PID);

-- Tuer une connexion (dernier recours)
SELECT pg_terminate_backend(PID);
```

⚠️ **Attention** : Ne pas tuer l'ingestion ou le compute_code_stats en cours !

---

## Vérification état ingestion

### Commandes
```bash
# Processus
ps aux | grep ingest_legifrance_pg | grep -v grep

# Logs
tail -f /tmp/ingest_legi_v3.log

# Nombre de documents
sudo -u legifrance_app psql -d legifrance -c "SELECT doctype, COUNT(*) FROM documents WHERE source = 'LEGI' GROUP BY doctype;"

# Taille DB
sudo -u legifrance_app psql -d legifrance -c "SELECT pg_size_pretty(pg_database_size('legifrance'));"
```

### Estimation progression
```bash
# Voir la dernière archive ingérée
tail -20 /tmp/ingest_legi_v3.log | grep "Done"

# Calculer % progression
# Total archives = 194 (1 freemium + 193 incremental)
# Archives done = compter les lignes "Done" dans le log
```

---

## Test CLI après modifications

### Test `list_codes`
```bash
time sudo -u legifrance_app python3 /mnt/legifrance/repo/legifrance/scripts/legi_cli.py list_codes --scope=codes_en_vigueur
# Attendu : < 1 seconde
```

### Test `get_articles`
```bash
time sudo -u legifrance_app python3 /mnt/legifrance/repo/legifrance/scripts/legi_cli.py get_articles --ids=LEGIARTI000006577453,LEGIARTI000006577454,LEGIARTI000006577455
# Attendu : < 10 secondes
```

### Test `get_code`
```bash
time sudo -u legifrance_app python3 /mnt/legifrance/repo/legifrance/scripts/legi_cli.py get_code --code_id=LEGITEXT000005634379 --depth=2
# Attendu : < 5 secondes (après ajout colonne code_id)
```

---

## Nettoyage inodes (si saturation)

### Diagnostic
```bash
df -i /mnt/data
# Si > 95% : URGENT
```

### Solution
```bash
# Supprimer les extractions (si elles existent encore)
sudo rm -rf /mnt/data/legifrance/data/*
sudo rm -rf /mnt/data/legifrance/current/*

# Supprimer vieux logs
sudo find /root/legifrance/logs -name "*.log" -mtime +30 -delete

# Vérifier
df -i /mnt/data
```

⚠️ **Ne jamais** relancer l'extraction historique (dossiers datés) !
