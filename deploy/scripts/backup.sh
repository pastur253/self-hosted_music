#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
ARCHIVE="$BACKUP_DIR/backup-$STAMP.tar.gz"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$BACKUP_DIR" "$WORK"

log "Бэкап Navidrome (CLI)"
docker compose exec -T navidrome navidrome backup >/dev/null

log "Снимок тома Navidrome"
docker run --rm -v "${COMPOSE_PROJECT_NAME:-self-hosted-music}_navidrome:/src:ro" \
  -v "$WORK:/dst" alpine:3.20 \
  sh -c 'cd /src && tar cf - --exclude=./cache .' | tar -xf - -C "$WORK" 2>/dev/null \
  || log "Имя тома Navidrome отличается — пропускаю (используйте navidrome backup)"

log "Снимок тома состояния MixCore (mix_data)"
docker run --rm -v "${COMPOSE_PROJECT_NAME:-self-hosted-music}_mix_data:/src:ro" \
  -v "$WORK/mixcore_state:/dst" alpine:3.20 \
  sh -c 'cd /src && tar cf - .' | tar -xf - -C "$WORK"

log "Копирование конфигурации"
mkdir -p "$WORK/config"
cp -r ./config "$WORK/config" 2>/dev/null || true
cp ./.env.example "$WORK/env.example" 2>/dev/null || true

log "Архивирование"
tar -czf "$ARCHIVE" -C "$WORK" .

log "Проверка архива"
tar -tzf "$ARCHIVE" >/dev/null

log "Удаление старых бэкапов (>${RETENTION_DAYS} дней)"
find "$BACKUP_DIR" -name 'backup-*.tar.gz' -type f -mtime "+$RETENTION_DAYS" -delete

log "Готово: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"