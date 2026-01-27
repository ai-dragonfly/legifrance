# Memory Bank — Documentation système Légifrance

Ce dossier contient la **mémoire opérationnelle** du système Légifrance (serveur PostgreSQL + CLI + MCP tools).

## 📁 Structure

### Documents de référence
- **`ARCHITECTURE.md`** : Vue d'ensemble système (composants, flux, règles)
- **`INFRA_HETZNER.md`** : Configuration serveur Hetzner (hardware, réseau, volumes)
- **`DATA_LAYOUT.md`** : Organisation données sur serveur (dossiers, archives, DB)

### Scripts et outils
- **`SCRIPTS_REFERENCE.md`** : Documentation détaillée de chaque script Python
- **`MCP_TOOLS.md`** : Outils MCP utilisés (`ssh_client`, `legifrance_legi`)
- **`PIPELINE_DAILY.md`** : Pipeline quotidien (téléchargement, ingestion, stats)

### Opérations
- **`CHANGELOG_OPERATIONS.md`** : Journal chronologique des changements infra
- **`OPS_RUNBOOK.md`** : Procédures de dépannage (inodes, corruption, locks)
- **`OPS_PROCEDURES.md`** : Procédures spécifiques (ajout colonne, recalcul stats, etc.)

### Performance
- **`PERFORMANCE.md`** : Métriques, benchmarks, optimisations appliquées

### Sessions
- **`SESSION_YYYY-MM-DD.md`** : Récapitulatif détaillé de chaque session de travail

---

## 🎯 Pour commencer

### Nouvelle IA reprenant le projet
1. Lire **`ARCHITECTURE.md`** (vue d'ensemble)
2. Lire **`CHANGELOG_OPERATIONS.md`** (historique)
3. Lire la dernière **`SESSION_*.md`** (état actuel)

### Ajouter une nouvelle fonctionnalité
1. Consulter **`SCRIPTS_REFERENCE.md`** (conventions)
2. Mettre à jour **`CHANGELOG_OPERATIONS.md`** (après déploiement)
3. Créer nouveau **`SESSION_*.md`** (documentation)

### Dépanner un problème
1. Consulter **`OPS_RUNBOOK.md`** (procédures standard)
2. Vérifier **`PERFORMANCE.md`** (métriques attendues)
3. Logger dans **`CHANGELOG_OPERATIONS.md`** (si changement infra)

---

## 📊 État actuel (2026-01-25)

### Système opérationnel
- ✅ PostgreSQL 14 avec 1.89M documents LEGI
- ✅ CLI `legi_cli.py` fonctionnel (`list_codes`, `get_articles`)
- ✅ Pipeline quotidien configuré (`daily_pipeline.py`)
- ✅ Table `code_stats` pour pré-calcul statistiques

### En cours
- ⏳ Ingestion LEGI (98% terminé, 191/194 archives)
- ⏳ Compute code stats (0.03% terminé, 79/288K textes)

### En attente
- 🔧 Ajout colonne `code_id` dénormalisée (bloqué par ingestion)
- 🔧 Optimisation `get_code` (après ajout `code_id`)
- 📅 Déploiement systemd timer pipeline quotidien

---

## 🔗 Liens utiles

### Serveur
- **IP** : YOUR_SERVER_IP
- **SSH** : `ssh root@YOUR_SERVER_IP` (clé ~/.ssh/id_rsa)
- **User app** : `legifrance_app` (UID 998)

### Chemins importants
- Scripts : `/root/legifrance/scripts/`
- CLI : `/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`
- Logs : `/root/legifrance/logs/`
- Archives : `/mnt/data/legifrance/archives/`

### PostgreSQL
- DB : `legifrance`
- Tables : `documents`, `code_stats`
- Connexion : `sudo -u legifrance_app psql -d legifrance`

---

## 📝 Convention nommage sessions

Format : `SESSION_YYYY-MM-DD.md`

Contenu recommandé :
- 🎯 Objectifs de la session
- ✅ Réalisations
- 🐛 Problèmes identifiés
- 📊 État système
- 🎯 Actions en attente
- 💡 Leçons apprises

---

## 🚨 Règles critiques

1. **INODES** : Ne jamais extraire l'historique sur filesystem → saturation garantie
2. **Locks** : Vérifier absence de verrous avant ALTER TABLE ou CREATE INDEX
3. **Backups** : Toujours sauvegarder fichiers avant modification (backup auto)
4. **Logs** : Tous les scripts longs doivent logger (horodatage + état)
5. **State** : Tous les jobs longs doivent avoir un state file (reprise possible)

---

## 📞 Contact

Projet : dragonfly-mcp-server-legifrance  
Repo local : `server_legifrance/`  
Memory bank : `server_legifrance/memory_bank/`
