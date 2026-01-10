#!/bin/bash
# Daily automation: download incremental archives + incremental reindex

set -e

REPO_DIR="/mnt/legifrance/repo/legifrance"
LOG_DIR="$REPO_DIR/logs"
DATE=$(date +%Y%m%d)

exec > >(tee -a "$LOG_DIR/cron_update_$DATE.log") 2>&1

echo "==================================================="
echo "START DAILY UPDATE: $(date)"
echo "==================================================="

cd "$REPO_DIR"
source .venv/bin/activate

# 1) Download DAILY sources

echo ""
echo "Downloading DAILY sources (JORF, JADE)..."
python scripts/update_archives.py --daily

# 2) Incremental reindex DAILY sources
# Rule A: if DB exists → reindex; else → initial index

echo ""
echo "Indexing DAILY sources..."

for source in jorf jade; do
  INDEX_DB="$REPO_DIR/sqlite3/index_${source}_prod.db"
  ARCHIVE_ROOT="$REPO_DIR/archives/${source^^}"

  echo " - $source"
  if [ -f "$INDEX_DB" ]; then
    python scripts/reindex_archives.py --index-name "${source}_prod" --archives-root "$ARCHIVE_ROOT" --verbose
  else
    python scripts/index_archives_fast.py --index-name "${source}_prod" --archives-root "$ARCHIVE_ROOT" --verbose
  fi

done

# 3) Download WEEKLY sources

echo ""
echo "Downloading WEEKLY sources (CASS, INCA, CAPP, CNIL, LEGI, KALI)..."
python scripts/update_archives.py --weekly

# 4) Incremental reindex WEEKLY sources

echo ""
echo "Indexing WEEKLY sources..."
for source in cass inca capp cnil legi kali; do
  INDEX_DB="$REPO_DIR/sqlite3/index_${source}_prod.db"
  ARCHIVE_ROOT="$REPO_DIR/archives/${source^^}"

  echo " - $source"
  if [ -f "$INDEX_DB" ]; then
    python scripts/reindex_archives.py --index-name "${source}_prod" --archives-root "$ARCHIVE_ROOT" --verbose
  else
    python scripts/index_archives_fast.py --index-name "${source}_prod" --archives-root "$ARCHIVE_ROOT" --verbose
  fi
done

# 5) Download MONTHLY sources

echo ""
echo "Downloading MONTHLY sources (CONSTIT)..."
python scripts/update_archives.py --monthly

# 6) Incremental reindex MONTHLY source

echo ""
echo "Indexing MONTHLY source..."
INDEX_DB="$REPO_DIR/sqlite3/index_constit_prod.db"
ARCHIVE_ROOT="$REPO_DIR/archives/CONSTIT"

if [ -f "$INDEX_DB" ]; then
  python scripts/reindex_archives.py --index-name constit_prod --archives-root "$ARCHIVE_ROOT" --verbose
else
  python scripts/index_archives_fast.py --index-name constit_prod --archives-root "$ARCHIVE_ROOT" --verbose
fi

echo ""
echo "==================================================="
echo "END DAILY UPDATE: $(date)"
echo "==================================================="
