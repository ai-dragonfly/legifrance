# 📖 Guide Utilisateur — Système Légifrance

**Version** : 3.1  
**Date** : 27 Janvier 2026  
**Public** : Développeurs, Data Scientists, Juristes techniques

---

## 🎯 Vue d'ensemble

Le système Légifrance vous permet d'interroger la base juridique française complète via :
- Une **API CLI** performante (`legi_cli.py`)
- Un **outil MCP** pour intégration IA (`legifrance_legi`)
- Des **données PostgreSQL** structurées et indexées

---

## 🚀 Démarrage Rapide

### **Installation (MCP Tool)**

Ajoutez dans votre configuration MCP :

```json
{
  "mcpServers": {
    "legifrance": {
      "command": "python",
      "args": ["-m", "dragonfly_mcp_server"],
      "env": {
        "SSH_HOST": "YOUR_SERVER_IP",
        "SSH_USER": "root",
        "SSH_KEY": "~/.ssh/id_rsa"
      }
    }
  }
}
```

### **Accès Direct SSH**

```bash
ssh root@YOUR_SERVER_IP
sudo -u legifrance_app psql -d legifrance
```

---

## 📚 Commandes CLI

### **1. list_codes — Lister les codes**

Liste tous les codes juridiques disponibles.

```bash
sudo -u legifrance_app python3 /mnt/legifrance/repo/legifrance/scripts/legi_cli.py \
  list_codes --scope=codes_en_vigueur
```

**Paramètres** :
- `--scope` : `codes_en_vigueur` | `codes_abroges` | `all` (défaut: codes_en_vigueur)

**Sortie** :
```json
{
  "codes": [
    {
      "code_id": "LEGITEXT000006072050",
      "titre": "Code du travail",
      "nature": "CODE",
      "etat": "VIGUEUR",
      "nb_articles": 64663,
      "nb_sections": 35585
    }
  ],
  "total": 170
}
```

**Performance** : < 0.5s

---

### **2. get_code — Arborescence hiérarchique**

Récupère l'arborescence d'un code juridique (Livres, Titres, Chapitres, Articles).

```bash
sudo -u legifrance_app python3 /mnt/legifrance/repo/legifrance/scripts/legi_cli.py \
  get_code \
  --code_id=LEGITEXT000006072050 \
  --depth=3 \
  --page=1 \
  --per_page=50
```

**Paramètres** :
- `--code_id` : ID du code (LEGITEXT...) — **OBLIGATOIRE**
- `--depth` : Profondeur (1-10, défaut: 3)
- `--include_articles` : Inclure les articles au dernier niveau
- `--root_section_id` : Partir d'une section spécifique (optionnel)
- `--page` : Numéro de page (défaut: 1)
- `--per_page` : Items par page (défaut: 50, max: 500)
- `--date` : Version à une date (YYYY-MM-DD, défaut: aujourd'hui)
- `--no-cache` : Forcer calcul sans cache

**Sortie** :
```json
{
  "code_id": "LEGITEXT000006072050",
  "titre": "Code du travail",
  "nature": "CODE",
  "tree": [
    {
      "id": "LEGISCTA000006123849",
      "titre": "Livre Ier : Conventions relatives au travail",
      "nb_sections": 245,
      "nb_articles": 1852,
      "children": [
        {
          "id": "LEGISCTA000006123851",
          "titre": "Titre Ier : Conventions relatives aux salaires",
          "nb_sections": 12,
          "nb_articles": 89,
          "children": [...]
        }
      ]
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 50,
    "total": 3469
  }
}
```

**Performance** :
- **Avec cache** : 0.6-1.5s (tous depths)
- **Sans cache** : 7-90s selon complexité

---

### **3. get_articles — Contenu des articles**

Récupère le contenu détaillé d'un ou plusieurs articles.

```bash
sudo -u legifrance_app python3 /mnt/legifrance/repo/legifrance/scripts/legi_cli.py \
  get_articles \
  --ids=LEGIARTI000006900001,LEGIARTI000006900002 \
  --include_links \
  --include_breadcrumb
```

**Paramètres** :
- `--ids` : IDs articles séparés par virgules (LEGIARTI...) — **OBLIGATOIRE**
- `--date` : Version à une date (YYYY-MM-DD, défaut: aujourd'hui)
- `--include_links` : Inclure liens juridiques (défaut: true)
- `--include_breadcrumb` : Inclure fil d'Ariane (défaut: true)

**Sortie** :
```json
{
  "articles": [
    {
      "id": "LEGIARTI000006900001",
      "num": "L1111-1",
      "titre": "Article sur les conventions...",
      "date_debut": "2008-05-01",
      "date_fin": "2999-01-01",
      "etat": "VIGUEUR",
      "content_text": "Les dispositions du présent code...",
      "breadcrumb": [
        "LEGITEXT000006072050 - Code du travail",
        "LEGISCTA000006123849 - Livre Ier",
        "LEGISCTA000006123851 - Titre Ier"
      ],
      "links": [
        {
          "type": "CITATION",
          "target_id": "LEGIARTI000006900123",
          "target_titre": "Article L2222-3"
        }
      ]
    }
  ],
  "total": 2
}
```

**Performance** : ~5s pour 3 articles

---

## 🎨 Exemples d'Utilisation

### **Exemple 1 : Explorer le Code du travail**

```bash
# 1. Lister tous les codes
legi_cli.py list_codes | jq '.codes[] | select(.titre | contains("travail"))'

# 2. Voir structure Livre I
legi_cli.py get_code --code_id=LEGITEXT000006072050 --depth=2 | \
  jq '.tree[] | select(.titre | contains("Livre I"))'

# 3. Récupérer articles Titre I
legi_cli.py get_code --code_id=LEGITEXT000006072050 --depth=3 --include_articles | \
  jq '.tree[0].children[0].articles'
```

### **Exemple 2 : Recherche par date**

```bash
# Version du Code pénal au 1er janvier 2020
legi_cli.py get_code \
  --code_id=LEGITEXT000006070719 \
  --depth=3 \
  --date=2020-01-01
```

### **Exemple 3 : Pagination gros volumes**

```bash
# Page 1 (50 premiers livres)
legi_cli.py get_code --code_id=LEGITEXT000006072050 --depth=1 --page=1 --per_page=50

# Page 2 (50 suivants)
legi_cli.py get_code --code_id=LEGITEXT000006072050 --depth=1 --page=2 --per_page=50

# Total pages : ceil(3469 / 50) = 70 pages
```

---

## 🔍 Utilisation MCP Tool (via IA)

### **Prompts recommandés**

**Liste des codes** :
```
"Donne-moi la liste des codes juridiques en vigueur"
```

**Exploration hiérarchique** :
```
"Affiche l'arborescence du Code du travail (Livre I, profondeur 3)"
```

**Recherche articles** :
```
"Trouve les articles du Code pénal sur les atteintes aux personnes"
```

**Analyse comparative** :
```
"Compare les articles L1111-1 et L1111-2 du Code du travail"
```

---

## 📊 Accès SQL Direct

### **Connexion**

```bash
sudo -u legifrance_app psql -d legifrance
```

### **Requêtes utiles**

**Compter documents** :
```sql
SELECT doctype, COUNT(*) 
FROM documents 
WHERE source='LEGI' 
GROUP BY doctype;
```

**Chercher code par titre** :
```sql
SELECT meta->>'id', meta->>'titre' 
FROM documents 
WHERE doctype='texte' 
  AND meta->>'titre' ILIKE '%travail%';
```

**Sections d'un code** :
```sql
SELECT meta->>'id', meta->>'titre'
FROM documents
WHERE doctype='section'
  AND meta->>'parent' = 'LEGITEXT000006072050'
LIMIT 10;
```

**Articles en vigueur** :
```sql
SELECT meta->>'num', meta->>'titre'
FROM documents
WHERE doctype='article'
  AND meta->>'etat' = 'VIGUEUR'
  AND meta->>'date_debut' <= '2026-01-26'
  AND meta->>'date_fin' > '2026-01-26'
LIMIT 10;
```

---

## ⚡ Optimisations

### **Cache automatique**

Le système utilise un cache pré-calculé pour **171 codes** :
- Arborescences depth=10 complètes
- Mise à jour automatique quotidienne
- Invalidation intelligente sur modifications

**Forcer recalcul** :
```bash
legi_cli.py get_code --code_id=LEGITEXT000006072050 --depth=3 --no-cache
```

### **Pagination optimale**

- **50 items/page** : Temps réponse <1s
- **100 items/page** : Temps réponse <2s
- **500 items/page** : Temps réponse <5s (max recommandé)

### **Depth recommandés**

| Depth | Utilisation | Performance |
|-------|-------------|-------------|
| **1** | Vue d'ensemble (Livres/Parties) | 0.6s |
| **2** | Navigation rapide (Titres) | 0.8s |
| **3** | Exploration détaillée (Chapitres) | 1.1s |
| **5** | Analyse approfondie | 1.3s |
| **10** | Arbre complet | 1.5s |

---

## 🐛 Dépannage

### **Erreur : "Code not found"**

Vérifiez l'ID du code :
```bash
legi_cli.py list_codes | grep "LEGITEXT..."
```

### **Timeout sur gros codes**

Utilisez pagination :
```bash
legi_cli.py get_code --code_id=XXX --depth=1 --per_page=100
```

### **Cache obsolète**

Forcez régénération :
```bash
sudo -u legifrance_app python3 /root/legifrance/scripts/precalculate_all_trees.py \
  --code-id=LEGITEXT000006072050 --force
```

### **Performance lente**

Vérifiez état cache :
```sql
SELECT code_id, updated_at, NOW() - updated_at as age
FROM code_trees
WHERE code_id = 'LEGITEXT000006072050';
```

Si `age > 24h`, régénérer :
```bash
sudo -u legifrance_app python3 /root/legifrance/scripts/regenerate_stale_caches.py
```

---

## 📞 Support

### **Logs**

- **CLI** : `/tmp/legi_cli_*.log`
- **Pipeline** : `/root/legifrance/logs/pipeline_*.log`
- **Cache** : Requête SQL `SELECT * FROM cache_invalidations`

### **Monitoring**

```bash
# État pipeline
systemctl status legifrance-pipeline.timer

# Derniers logs
journalctl -u legifrance-pipeline -n 50

# État DB
sudo -u legifrance_app psql -d legifrance -c "\dt+"
```

### **Contact**

- **Documentation** : `/server_legifrance/memory_bank/`
- **Runbook** : `OPS_RUNBOOK.md`
- **Architecture** : `ARCHITECTURE.md`

---

## 🔐 Bonnes Pratiques

### **Sécurité**

- ✅ Toujours utiliser `sudo -u legifrance_app` pour PostgreSQL
- ✅ Ne jamais exposer SSH publiquement
- ✅ Sauvegarder DB régulièrement (`pg_dump`)

### **Performance**

- ✅ Préférer pagination pour >100 items
- ✅ Utiliser cache (--no-cache uniquement si nécessaire)
- ✅ Limiter depth à 3-5 pour exploration

### **Fiabilité**

- ✅ Vérifier `updated_at` des caches
- ✅ Surveiller inodes `/mnt/data` (seuil 90%)
- ✅ Tester avec petits codes d'abord

---

## 📚 Ressources

- **DILA Open Data** : https://echanges.dila.gouv.fr/OPENDATA/
- **Légifrance** : https://www.legifrance.gouv.fr/
- **PostgreSQL JSONB** : https://www.postgresql.org/docs/14/datatype-json.html

---

**Dernière mise à jour** : 27 Janvier 2026  
**Version système** : 3.1 (Correctifs articles + Phase 4)
