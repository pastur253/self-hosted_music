#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-./backups}"
TARGET="${1:-/tmp/mixcore-restore-check}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

LATEST="$(ls -1t "$BACKUP_DIR"/backup-*.tar.gz 2>/dev/null | head -n1 || true)"
[ -n "$LATEST" ] || { printf 'Нет архивов бэкапа в %s\n' "$BACKUP_DIR" >&2; exit 1; }

log "Проверка архива $LATEST"
rm -rf "$TARGET"
mkdir -p "$TARGET"
tar -xzf "$LATEST" -C "$TARGET"

log "Целостность файлов состояния"
FAILED=0
while IFS= read -r file; do
  case "$file" in
    *.gz) gzip -t "$file" || FAILED=1 ;;
    *.json)
      python3 -c "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))" "$file" || FAILED=1
      ;;
    *.jsonl)
      python3 - "$file" <<'PY' || FAILED=1
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line:
        json.loads(line)
PY
      ;;
  esac
done < <(find "$TARGET" -type f \( -name '*.json' -o -name '*.jsonl' -o -name '*.gz' \) ! -path '*/cache/*')

[ "$FAILED" -eq 0 ] || { printf 'Найдены повреждённые файлы состояния\n' >&2; exit 1; }

log "Версия схемы состояния"
cat "$TARGET/mixcore_state/.schema_version" 2>/dev/null || printf 'файла нет (состояние не инициализировано)\n'

log "Состав архива"
du -sh "$TARGET"/* 2>/dev/null || true

log "Проверка пройдена. Боевое восстановление — по docs/runbook.md (шаг «Восстановление»)"
log "OK"