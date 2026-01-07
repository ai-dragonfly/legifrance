# Scripts Légifrance

## 🚀 Première utilisation

### Téléchargement initial complet
```bash
python download_archives.py --all
```

### Téléchargement par type
```bash
# Freemium uniquement (données complètes)
python download_archives.py --freemium

# Archives incrémentales uniquement
python download_archives.py --incremental
```

### Source spécifique
```bash
python download_archives.py --source JADE --all
python download_archives.py --source LEGI --freemium
```

---

## 🔄 Mises à jour

### Mise à jour intelligente (recommandé)
```bash
python update_archives.py
```
Télécharge uniquement les nouvelles archives selon la fréquence de chaque source.

### Forcer la mise à jour
```bash
python update_archives.py --force
```

### Mise à jour par source
```bash
python update_archives.py --source JADE
python update_archives.py --source LEGI --force
```

### Mise à jour par fréquence
```bash
python update_archives.py --daily      # JADE, JORF
python update_archives.py --weekly     # CASS, INCA, CAPP, CNIL, LEGI, KALI
```

---

## 📊 Statut

```bash
python download_archives.py --status
python update_archives.py --status
```

---

## 📅 Téléchargement depuis une date

```bash
python download_archives.py --incremental --since 20250101
python download_archives.py --source JADE --incremental --since 20241201
```

---

## 🗂️ Sources disponibles

**Jurisprudence :** CASS, INCA, CAPP, JADE, CONSTIT, CNIL  
**Codes/Lois :** LEGI, JORF, KALI

---

## 📝 Logs

- Téléchargements : `../logs/download_YYYYMMDD_HHMMSS.log`
- Mises à jour : `../logs/update_YYYYMMDD_HHMMSS.log`
- État : `../config/download_state.json`

---

## 💡 Workflow recommandé

```bash
# 1. Premier téléchargement
python download_archives.py --all

# 2. Vérifier le statut
python download_archives.py --status

# 3. Mises à jour quotidiennes (cron/planificateur)
python update_archives.py --daily

# 4. Mises à jour hebdomadaires
python update_archives.py --weekly
```
