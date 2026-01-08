#!/bin/bash
# /mnt/legifrance/repo/legifrance/scripts/daily_update.sh
# Script d'automatisation quotidienne : Download incremental + Reindex

# Exit on error
set -e

# Config
REPO_DIR="/mnt/legifrance/repo/legifrance"
LOG_DIR="$REPO_DIR/logs"
DATE=$(date +%Y%m%d)

# Setup log
exec > >(tee -a "$LOG_DIR/cron_update_$DATE.log") 2>&1

echo "==================================================="
echo "🚀 START DAILY UPDATE: $(date)"
echo "==================================================="

cd "$REPO_DIR"
source .venv/bin/activate

# 1. Update DAILY sources (JORF, JADE)
echo ""
echo "📥 Downloading DAILY sources (JORF, JADE)..."
python scripts/update_archives.py --daily

echo ""
echo "⚙️  Indexing DAILY sources..."
python scripts/index_archives_fast.py --index-name jorf_prod --archives-root archives/JORF --verbose
python scripts/index_archives_fast.py --index-name jade_prod --archives-root archives/JADE --verbose

# 2. Update WEEKLY sources (Run everyday, script handles frequency check)
echo ""
echo "📥 Downloading WEEKLY sources (CASS, INCA, CAPP, CNIL, LEGI, KALI)..."
python scripts/update_archives.py --weekly

echo ""
echo "⚙️  Indexing WEEKLY sources..."
for source in cass inca capp cnil legi kali; do
    echo " -> Indexing ${source}..."
    python scripts/index_archives_fast.py \
        --index-name "${source}_prod" \
        --archives-root "archives/${source^^}" \
        --verbose
done

# 3. Update MONTHLY sources (CONSTIT)
echo ""
echo "📥 Downloading MONTHLY sources (CONSTIT)..."
python scripts/update_archives.py --monthly

echo ""
echo "⚙️  Indexing MONTHLY sources..."
python scripts/index_archives_fast.py --index-name constit_prod --archives-root archives/CONSTIT --verbose

echo ""
echo "==================================================="
echo "✅ END DAILY UPDATE: $(date)"
echo "==================================================="
