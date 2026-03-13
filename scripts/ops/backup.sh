#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
BACKUP_ROOT="${BACKUP_ROOT:-${PROJECT_ROOT}/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

DB_DIR="${BACKUP_ROOT}/db"
MEDIA_DIR="${BACKUP_ROOT}/media"

mkdir -p "${DB_DIR}" "${MEDIA_DIR}"

cd "${PROJECT_ROOT}"

DB_FILE="${DB_DIR}/recap_db_${TIMESTAMP}.sql.gz"
MEDIA_FILE="${MEDIA_DIR}/recap_media_${TIMESTAMP}.tar.gz"
TMP_DB_FILE="${DB_FILE}.tmp"

if ! docker compose ps --status running --services | grep -qx 'db'; then
  echo "[backup] db service is not running, starting db"
  docker compose up -d db
fi

echo "[backup] dumping postgres to ${DB_FILE}"
rm -f "${TMP_DB_FILE}"
if docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "${TMP_DB_FILE}"; then
  mv "${TMP_DB_FILE}" "${DB_FILE}"
else
  rm -f "${TMP_DB_FILE}"
  echo "[backup] postgres dump failed"
  exit 1
fi

echo "[backup] archiving media to ${MEDIA_FILE}"
if [ -d "${PROJECT_ROOT}/media" ]; then
  tar -czf "${MEDIA_FILE}" -C "${PROJECT_ROOT}" media
else
  echo "[backup] media directory not found, creating empty archive"
  tar -czf "${MEDIA_FILE}" --files-from /dev/null
fi

echo "[backup] cleaning files older than ${RETENTION_DAYS} days"
find "${DB_DIR}" -type f -name '*.sql.gz' -mtime +"${RETENTION_DAYS}" -delete
find "${MEDIA_DIR}" -type f -name '*.tar.gz' -mtime +"${RETENTION_DAYS}" -delete

echo "[backup] done"
echo "[backup] db: ${DB_FILE}"
echo "[backup] media: ${MEDIA_FILE}"
