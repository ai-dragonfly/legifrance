# 🏛️ Système Légifrance — Infrastructure Production

**Version** : 3.1  
**Statut** : ✅ Production-Ready  
**Dernière mise à jour** : 27 Janvier 2026

---

## 📋 Vue d'ensemble

Système automatisé d'ingestion, indexation et interrogation de la base juridique française complète (LégifranceDILA Open Data).

### **Fonctionnalités principales**

✅ **Ingestion PostgreSQL** : 3.9M documents juridiques (codes + textes)  
✅ **Hiérarchie complète** : Navigation depth=10 (Livre → Titre → Chapitre → Article)  
✅ **Cache intelligent** : Arbores pré-calculés, invalidation automatique  
✅ **API CLI performante** : <1.5s pour toutes requêtes  
✅ **Tool MCP** : Intégration IA (Claude, GPT, etc.)  
✅ **Pipeline quotidien** : Mise à jour automatique 04:00 UTC  

### **Performance**

| Opération | Performance | Cache | Gain vs calcul dyna|-----------|-------------|-------|--------------------------|
| **list_codes** | 0.4s | ✅ | - |
| **get_code depth=1** | 0.6s | ✅ | 13x |
| **get_code depth=3** | 1.1s | ✅ | 14x |
| **get_code depth=10** | 1.5s | ✅ | 60x |
| **get_articles** | 5s | - | - |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DILA Open Data                           │
│         (Archives quotidiennes tar.gz)                      │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────────┐
│          Pipeline Quotidien (04:00 UTC)                     │
│  1. Download  2. Integrity  3. Ingest  4. Stats  5. Cache  │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────────┐
│                  PostgreSQL 14                              │
│  • documents (3.9M rows, 17 GB)                             │
│  • code_stats (171 codes, métadonnées)                      │
│  • code_trees (171 arbres depth=10, 115 MB cache)           │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ↓
┌─────────────────────────────────────────────────────────────┐
│              API/CLI (legi_cli.py v3.0)                     │
│  • list_codes  • get_code  • get_articles                   │
└──────────────────────┬──────────────────────────────────────┘
                       │
            ┌──────────┴──────────┐
            ↓                     ↓
    ┌──────────────┐      ┌──────────────┐
    │  MCP Tool    │      │  Direct SSH  │
    │  (Claude AI) │      │  (psql)      │
    └──────────────┘      └──────────────┘
```

---

## 🚀 Démarrage Rapide

### **Prérequis**

- Serveur : Ubuntu 22.04 (Hetzner)
- PostgreSQL 14
- Python 3.10+
- SSH avec clé publique

### **Installation**

```bash
# 1. Clone le repo
git clone https://github.com/your-org/dragonfly-mcp-server-legifrance.git
cd dragonfly-mcp-server-legifrance

# 2. Deploy sur serveur
cd server_legifrance/deploy
bash deploy_systemd.sh

# 3. Lancement pipeline initial
sudo systemctl start legifrance-pipeline
```

### **Utilisation**

**Via CLI** :
```bash
# Lister codes
sudo -u legifrance_app python3 /mnt/legifrance/repo/legifrance/scripts/legi_cli.py list_codes

# Arborescence Code du travail
sudo -u legifrance_app python3 /mnt/legifrance/repo/legifrance/scripts/legi_cli.py \
  get_code --code_id=LEGITEXT000006072050 --depth=3
```

**Via MCP (AI)** :
```
"Donne-moi la structure du Code du travail, Livre I, profondeur 3"
```

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[USER_GUIDE.md](USER_GUIDE.md)** | 📖 Manuel utilisateur complet |
| **[memory_bank/ARCHITECTURE.md](memory_bank/ARCHITECTURE.md)** | 🏗️ Architecture système |
| **[memory_bank/SCRIPTS_REFERENCE.md](memory_bank/SCRIPTS_REFERENCE.md)** | 📜 Référence scripts |
| **[memory_bank/PERFORMANCE.md](memory_bank/PERFORMANCE.md)** | ⚡ Métriques & optimisations |
| **[memory_bank/OPS_RUNBOOK.md](memory_bank/OPS_RUNBOOK.md)** | 🚨 Procédures dépannage |

---

## 🔧 Scripts Production

| Script | Version | Fonction | Durée |
|--------|---------|----------|-------|
| `download_archives.py` | v1 | Téléchargement DILA | ~30 min |
| `check_integrity.py` | v1 | Vérification intégrité | ~5 min |
| `ingest_legifrance_pg.py` | **v3.0** | Ingestion PostgreSQL | ~60 min |
| `compute_code_stats_v2.py` | v2 | Stats codes | **19s** |
| `precalculate_all_trees.py` | **v2** | Génération cache | **3.8 min** |
| `regenerate_stale_caches.py` | v1 | Maintenance cache | 5-15 min |
| `legi_cli.py` | **v3.0** | API CLI | <1.5s |
| `daily_pipeline.py` | **v2.0** | Orchestrateur | ~1h40 |

---

## 📊 Métriques Clés

### **Base de données**
- **Documents** : 3,955,949
- **Taille** : 17 GB
- **Articles** : 3,098,351 (78.3%)
- **Sections** : 409,529 (10.4%)
- **Textes** : 422,953 (10.7%)

### **Hiérarchie**
- **Sections avec parent** : 173,625 (42.4%)
- **Sections avec sous-sections** : 148,712 (36.3%)
- **Sections avec articles** : 283,134 (69.1%)

### **Cache**
- **Codes cachés** : 171 / 171 (100%)
- **Taille cache** : 115 MB
- **Trigger invalidation** : Automatique
- **Régénération** : Quotidienne (codes modifiés)

---

## ⚡ Performance

### **Gains mesurés**

| Optimisation | Avant | Après | Gain |
|--------------|-------|-------|------|
| **Ingestion** | 5 jours | 1 heure | **120x** |
| **Compute stats** | 47 jours | 19 secondes | **8,500x** |
| **get_code (cache)** | 7-90s | 0.6-1.5s | **13-60x** |
| **Précalcul cache** | 12-48h | 3.8 min | **475x** |

### **Benchmarks**

```bash
# Benchmark list_codes
time legi_cli.py list_codes
# ✅ real 0m0.440s

# Benchmark get_code depth=3 (avec cache)
time legi_cli.py get_code --code_id=LEGITEXT000006072050 --depth=3
# ✅ real 0m1.100s

# Benchmark get_code depth=10 (avec cache)
time legi_cli.py get_code --code_id=LEGITEXT000006072050 --depth=10
# ✅ real 0m1.500s
```

---

## 🛠️ Maintenance

### **Pipeline quotidien (Automatique)**

```bash
# Timer systemd (04:00 Europe/Paris)
systemctl status legifrance-pipeline.timer

# Logs
journalctl -u legifrance-pipeline -f

# Forcer exécution manuelle
sudo systemctl start legifrance-pipeline
```

### **Monitoring**

```sql
-- État cache
SELECT COUNT(*) FROM code_trees WHERE updated_at > NOW() - INTERVAL '24 hours';

-- Invalidations récentes
SELECT reason, COUNT(*) FROM cache_invalidations 
WHERE triggered_at > NOW() - INTERVAL '24 hours'
GROUP BY reason;

-- Sanity check
SELECT doctype, COUNT(*) FROM documents GROUP BY doctype;
```

### **Alertes**

| Métrique | Seuil | Action |
|----------|-------|--------|
| **Inodes /mnt/data** | >90% | ⚠️ Nettoyage archives anciennes |
| **DB size** | >250 GB | ⚠️ Archivage textes abrogés |
| **Cache obsolète** | >10 codes | ⚠️ Vérifier triggers |
| **Pipeline failed** | Exit code ≠ 0 | 🚨 Consulter OPS_RUNBOOK.md |

---

## 🔐 Sécurité

- ✅ User système `legifrance_app` (UID 998)
- ✅ PostgreSQL peer auth (pas de password)
- ✅ SSH key-based authentication
- ✅ Firewall : SSH uniquement (port 22)
- ✅ Backups quotidiens (pg_dump)
- ✅ Logs rotation automatique

---

## 📞 Support

### **Logs**

```bash
# Ingestion
tail -f /root/legifrance/logs/ingest_pg_*.log

# Pipeline
tail -f /root/legifrance/logs/pipeline_*.log

# Systemd
journalctl -u legifrance-pipeline -n 100
```

### **Dépannage**

Consulter : **[memory_bank/OPS_RUNBOOK.md](memory_bank/OPS_RUNBOOK.md)**

### **Contacts**

- **Repo** : https://github.com/your-org/dragonfly-mcp-server-legifrance
- **Memory Bank** : `server_legifrance/memory_bank/`
- **Changelog** : `memory_bank/CHANGELOG_OPERATIONS.md`

---

## 📜 Changelog

### **v3.1 (27 Janvier 2026)** — Correctifs critiques

- ✅ Correction 6 bugs `get_code --include_articles` (v3.0 → v3.1)
- ✅ Articles en VIGUEUR retournés correctement (était 0%, maintenant 100%)
- ✅ Suppression doublons articles (13x même ID corrigé)
- ✅ Filtrage versions historiques (VIGUEUR par défaut)
- ✅ Tri sections par `updated_at` (cohérence versions)

### **v3.0 (26 Janvier 2026)** — Phase 4 complète

- ✅ Hiérarchie depth=10 complète (STRUCTURE_TA)
- ✅ Cache automatique (171 codes)
- ✅ Triggers invalidation
- ✅ Maintenance quotidienne
- ✅ Performance <1.5s garantie

### **v2.0 (25 Janvier 2026)** — Optimisations

- ✅ Ingestion PostgreSQL (120x plus rapide)
- ✅ Compute stats (8,500x plus rapide)
- ✅ legi_cli.py v2.0 (hiérarchie exploitable)

### **v1.0 (25 Janvier 2026)** — Infrastructure initiale

- ✅ PostgreSQL 14 + table documents
- ✅ Scripts ingestion + pipeline
- ✅ CLI de base

---

## 📄 Licence

**Propriétaire** — Usage interne uniquement

**Source données** : DILA Open Data (domaine public)

---

## 🙏 Crédits

- **DILA** : Direction de l'Information Légale et Administrative
- **Légifrance** : Service public de la diffusion du droit
- **PostgreSQL** : The World's Most Advanced Open Source Relational Database

---

**🎉 Système Production-Ready — v3.1**

**Dernière validation** : 27 Janvier 2026 11:00 UTC
