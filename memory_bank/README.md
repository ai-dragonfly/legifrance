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
- **`SESSION_2026-01-25.md`** : Optimisation CLI + Pipeline
- **`SESSION_2026-01-26.md`** : Hiérarchie complète + Cache depth=10
- **`SESSION_2026-01-27.md`** : Correction bugs ingestion et code stats

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

## 📊 État actuel (2026-01-27)

### ✅ Système 100% opérationnel
- ✅ PostgreSQL 14 avec 2.5M documents LEGI
- ✅ CLI `legi_cli.py` fonctionnel (0 bugs)
- ✅ Pipeline quotidien automatisé (systemd timer 04:00)
- ✅ Cache depth=10 pré-calculé (171 codes, &lt;0.5s)
- ✅ Code stats à jour (77 VIGUEUR, 31 ABROGE)
- ✅ 0 doublons, 0 bugs connus

### Métriques production
- **Documents** : 2,516,208 (0 doublons)
- **Taille DB** : 11 GB
- **Codes VIGUEUR** : 77 (100% exact)
- **Codes ABROGE** : 31 (100% exact)
- **Performance** : list_codes 0.44s, get_code &lt;1.5s

---

## 🔗 Liens utiles

### Serveur
- **IP** : 188.245.151.223
- **SSH** : `ssh root@188.245.151.223` (clé ~/.ssh/id_rsa)
- **User app** : `legifrance_app` (UID 998)

### Chemins importants
- Scripts : `/root/legifrance/scripts/`
- CLI : `/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`
- Logs : `/root/legifrance/logs/`
- Archives : `/mnt/data/legifrance/archives/`

### PostgreSQL
- DB : `legifrance`
- Tables : `documents`, `code_stats`, `code_trees`
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
6. **Tests** : Toujours tester sur 1 archive avant ingestion complète
7. **Validation** : Pas de biais de confirmation, requêtes SQL exhaustives

---

## 📞 Contact

Projet : dragonfly-mcp-server-legifrance  
Repo local : `server_legifrance/`  
Memory bank : `server_legifrance/memory_bank/`  
Scripts miroir : `server_legifrance/mirror/`

**Dernière mise à jour** : 27 Janvier 2026 16:50 UTC
