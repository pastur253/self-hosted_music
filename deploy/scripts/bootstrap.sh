#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

log() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m!!\033[0m %s\n' "$*" >&2; exit 1; }

[ -f .env ] || { cp .env.example .env; log "Создан .env из .env.example — проверьте значения"; }
[ -d secrets ] || mkdir -p secrets

create_secret() {
  local path="$1" size="$2"
  if [ ! -s "$path" ]; then
    openssl rand -hex "$size" > "$path"
    chmod 600 "$path"
    log "Создан секрет $path"
  fi
}

create_secret secrets/navidrome_admin 24
create_secret secrets/gateway_token 32

log "Сборка образов"
docker compose build

log "Запуск стека"
docker compose up -d

log "Ожидание готовности MixCore"
for _ in $(seq 1 60); do
  if docker compose exec -T mixcore curl -fsS http://127.0.0.1:8080/healthz >/dev/null 2>&1; then
    log "MixCore готов"
    break
  fi
  sleep 2
done

log "Инициализация состояния"
docker compose exec -T mixcore python -m mixcore.cli --state-dir /var/lib/mixcore init-admin

log "Проверка"
docker compose exec -T mixcore python -m mixcore.cli --state-dir /var/lib/mixcore selftest || true

cat <<'EOF'

Готово. Дальше:

1. Создайте пользователей Navidrome:
   docker compose exec navidrome navidrome user create --admin
   docker compose exec navidrome navidrome user create
2. Положите учётные данные администратора в deploy/secrets/navidrome_admin (логин:пароль).
3. Синхронизируйте библиотеку:
   docker compose exec mixcore python -m mixcore.cli --state-dir /var/lib/mixcore sync-library
4. Создайте миксы:
   docker compose exec mixcore python -m mixcore.cli --state-dir /var/lib/mixcore seed --user <логин>
5. Откройте MixWeb: http://<домен>/  и подключите Feishin к http://<домен>/subsonic
6. Feishin в браузере (профиль client): docker compose --profile client up -d → http://<хост>:9180

EOF