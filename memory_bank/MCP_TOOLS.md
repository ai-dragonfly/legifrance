


# MCP_TOOLS — Outils MCP utilisés

## `ssh_client`
### Rôle
- Exécution de commandes sur le serveur (SSH)
- Transfert de fichiers (SFTP upload/download)
- Status de connexion

### Auth
- Principalement par clé SSH (`auth_type=key`) + passphrase

### Règles
- Ne pas logger secrets
- Timeouts adaptés : commandes longues à lancer en nohup
- Validation :
  - `rm -rf /` bloqué (strict)
  - `mkfs` autorisé (provisioning) — utiliser avec extrême prudence

### Modifications
- Validator assoupli pour autoriser `mkfs` et chemins `server_legifrance/`
- Support chemins locaux : `server_legifrance/` et `files/`

---

## `legifrance_legi` ⭐ NOUVEAU
### Rôle
Exposer les données LEGI (codes juridiques) au LLM via CLI distant.

### Opérations
- `list_codes(scope)` : liste codes en vigueur/abrogés
- `get_code(code_id, depth, include_articles, root_section_id)` : arborescence récursive
- `get_articles(ids, date, include_links, include_breadcrumb)` : contenu articles

### Mécanisme
1. Le tool MCP exécute via SSH : `/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`
2. Le CLI interroge PostgreSQL (peer auth `legifrance_app`)
3. Retourne JSON parsé par le tool

### Configuration (variables d'environnement)
- `LEGI_SSH_HOST` : IP serveur (YOUR_SERVER_IP)
- `LEGI_SSH_KEY` : chemin clé SSH (~/.ssh/id_rsa)
- `LEGI_CLI_PATH` : `/mnt/legifrance/repo/legifrance/scripts/legi_cli.py`
- `LEGI_TIMEOUT_*` : timeouts par opération

### Performances (état actuel)
| Opération | Temps | Statut | Méthode |
|-----------|-------|--------|---------|
| `list_codes` | **0.44s** | ✅ Opérationnel | Table `code_stats` (pré-calcul) |
| `get_articles` | **5s** | ✅ Opérationnel | Requête IN directe par IDs |
| `get_code` | Variable | ⏳ En test | Traverse via `meta->>'parent'` |

### Optimisations appliquées
- **v1** : Requêtes directes (timeout sur `list_codes`)
- **v2** : Utilise table `code_stats` pour `list_codes` → **0.44s** ⚡
- **v3** : Utilise index JSONB (`meta->>'parent'`) au lieu de `path LIKE`

### Specs
- Fichier : `src/tool_specs/legifrance_legi.json`
- Code : `src/tools/legifrance_legi.py`
- Module : `src/tools/_legifrance_legi/`

---

## Futur tool Légifrance (recommandation)
Nom proposé : `legifrance_manager` ou `legifrance_pipeline`.

Opérations envisagées :
- `status` (download/extract state + disk/inodes)
- `init_current`
- `daily_update`
- `integrity_check`
- `metrics`

Objectif : réduire l'usage de commandes shell arbitraires, standardiser les actions.

 
 
