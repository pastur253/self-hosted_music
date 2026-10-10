#!/usr/bin/env bash
set -euo pipefail
#
# Проверка целостности последнего бэкапа без развёртывания.
#   sudo /opt/music-stack/deploy/native/scripts/verify-restore-native.sh [каталог]

BACKUP_DIR="${BACKUP_DIR:-/var/backups/music-stack}"
TARGET="${1:-/tmp/music-restore-check}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

LATEST="$(ls -1t "$BACKUP_DIR"/backup-*.tar.gz 2>/dev/null | head -n1 || true)"
[ -n "$LATEST" ] || { printf 'Бэкапы не найдены в %s\n' "$BACKUP_DIR" >&2; exit 1; }

log "Архив: $LATEST"
rm -rf "$TARGET"
mkdir -p "$TARGET"
tar -xzf "$LATEST" -C "$TARGET"

log "Распаковка состояния MixCore для проверки"
mkdir -p "$TARGET/mixcore"
tar -xzf "$TARGET/mixcore.tgz" -C "$TARGET/mixcore"

FAILED=0
while IFS= read -r file; do
  case "$file" in
    *.gz) gzip -t "$file" || FAILED=1 ;;
    *.json)
      /opt/music-stack/venv/bin/python -c "import json,sys; json.load(open(sys.argv[1], encoding='utf-8'))" "$file" || FAILED=1
      ;;
    *.jsonl)
      /opt/music-stack/venv/bin/python - "$file" <<'PY' || FAILED=1
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line:
        json.loads(line)
PY
      ;;
  esac
done < <(find "$TARGET/mixcore" -type f \( -name '*.json' -o -name '*.jsonl' -o -name '*.gz' \))

if [ "$FAILED" -ne 0 ]; then
  printf 'Найдены повреждённые файлы состояния\n' >&2
  exit 1
fi

log "Версия схемы состояния"
cat "$TARGET/mixcore/mixcore/.schema_version" 2>/dev/null || echo "файл отсутствует (состояние не инициализировано)"

log "Состав"
du -sh "$TARGET"/* 2>/dev/null || true

log "Проверка пройдена. Боевое восстановление — docs/runbook.md, раздел «Восстановление»."
log "OK"