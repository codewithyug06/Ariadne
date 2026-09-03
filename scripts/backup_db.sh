#!/usr/bin/env bash
# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
#
# Consistent SQLite backup using the online backup API (via `sqlite3 .backup`,
# not `cp`) so it's safe to run against a live database with writers active.
# Run on a schedule (cron/systemd timer) against the same volume the
# `ariadne` container writes to.
#
#   ./scripts/backup_db.sh                       # backs up ./data/ariadne.db
#   ./scripts/backup_db.sh /path/to/ariadne.db ./backups
#
# Restore:
#   gunzip -k backups/ariadne_TIMESTAMP.db.gz
#   docker compose -f docker-compose.prod.yml stop ariadne
#   cp backups/ariadne_TIMESTAMP.db data/ariadne.db
#   docker compose -f docker-compose.prod.yml start ariadne

set -euo pipefail

DB_PATH="${1:-./data/ariadne.db}"
BACKUP_DIR="${2:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"

if [ ! -f "$DB_PATH" ]; then
  echo "No database at $DB_PATH — nothing to back up." >&2
  exit 1
fi

if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "sqlite3 CLI not found. Install it (apt: sqlite3, brew: sqlite) and retry." >&2
  exit 1
fi

mkdir -p "$BACKUP_DIR"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_FILE="${BACKUP_DIR}/ariadne_${TIMESTAMP}.db"

# The SQLite online backup API (`.backup`) takes a consistent snapshot even
# while the app is writing — unlike copying the file, which can grab a
# mid-write, corrupt state under WAL mode.
sqlite3 "$DB_PATH" ".backup '${OUT_FILE}'"
gzip -f "$OUT_FILE"

echo "Backed up ${DB_PATH} -> ${OUT_FILE}.gz"

# Prune backups older than RETENTION_DAYS. Compliance exports live
# separately (scripts/export_compliance_report.sh) and are not touched here.
find "$BACKUP_DIR" -name 'ariadne_*.db.gz' -mtime "+${RETENTION_DAYS}" -delete
echo "Pruned backups older than ${RETENTION_DAYS} days from ${BACKUP_DIR}."
