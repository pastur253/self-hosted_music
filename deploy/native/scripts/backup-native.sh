#!/usr/bin/env bash
set -euo pipefail
#
# Бэкап MusicStack без Docker.
#   Navidrome: /usr/local/bin/navidrome backup
#   MixCore:   /var/lib/music-stack/mixcore (файлы состояния)
#
# Запуск: sudo /opt/music-stack/deploy/native/scripts/backup-native.sh
# Проверка: sudo /opt/music-stack/deploy/native/scripts/verify-restore-native.sh

DATA_DIR="${DATA_DIR:-/var/lib/music-stack}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/music-stack}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"
ARCHIVE="$BACKUP_DIR/backup-$STAMP.tar.gz"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
trap 'rm -rf "$WORK"' EXIT

install -d -m 0750 "$BACKUP_DIR"

log "Снимок Navidrome"
runuser -u music -- env \
  ND_DATAFOLDER="$DATA_DIR/navidrome" \
  ND_CONFIGFILE=/etc/music-stack/navidrome.toml \
  /usr/local/bin/navidrome backup >/dev/null

log "Снимок состояния MixCore"
tar -czf "$WORK/mixcore.tgz" -C "$DATA_DIR" mixcore

log "Конфигурация и правила"
mkdir -p "$WORK/etc"
cp -r /etc/music-stack "$WORK/etc/music-stack"
chmod -R go-rwx "$WORK/etc/music-stack/secrets" 2>/dev/null || true

log "Сборка архива"
tar -czf "$ARCHIVE" -C "$WORK" .
tar -tzf "$ARCHIVE" >/dev/null

log "Ротация старых бэкапов (>${RETENTION_DAYS} дней)"
find "$BACKUP_DIR" -maxdepth 1 -name 'backup-*.tar.gz' -type f -mtime "+$RETENTION_DAYS" -delete

log "Готово: $ARCHIVE ($(du -h "$ARCHIVE" | cut -f1))"