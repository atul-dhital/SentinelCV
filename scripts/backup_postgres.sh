#!/usr/bin/env bash
# PostgreSQL backup script for SentinelCV.
# Dumps the production database, compresses it, and rotates old backups.
#
# Usage (manual):
#   ./scripts/backup_postgres.sh
#
# Usage (cron — daily at 2 AM):
#   0 2 * * * /path/to/sentinelcv/scripts/backup_postgres.sh >> /var/log/sentinelcv-backup.log 2>&1

set -euo pipefail

COMPOSE="docker compose -f docker-compose.prod.yml"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/sentinelcv}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
DB_USER="sentinelcv"
DB_NAME="sentinelcv_prod"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting backup → $BACKUP_FILE"

# Dump and compress in one pipe — no uncompressed file on disk
$COMPOSE exec -T postgres \
  pg_dump -U "$DB_USER" "$DB_NAME" \
  | gzip -9 > "$BACKUP_FILE"

SIZE=$(du -sh "$BACKUP_FILE" | cut -f1)
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Backup complete. Size: $SIZE"

# Rotate old backups
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Removing backups older than ${RETENTION_DAYS} days..."
find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete
REMAINING=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" | wc -l)
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Backup rotation done. ${REMAINING} backups retained."

# ── Optional: copy to remote storage ─────────────────────────────────────────
# Uncomment and configure one of the following:
#
# AWS S3:
#   aws s3 cp "$BACKUP_FILE" "s3://your-bucket/sentinelcv-backups/"
#
# Backblaze B2 (via rclone):
#   rclone copy "$BACKUP_FILE" b2:your-bucket/sentinelcv-backups/
#
# SFTP:
#   scp "$BACKUP_FILE" backup-user@backup-host:/backups/sentinelcv/
