#!/usr/bin/env bash
set -euo pipefail
#
# Установка MusicStack в WSL без Docker.
# Дистрибутивы: Ubuntu 24.04+ / Debian 12+ с включённым systemd.
#
#   sudo ./deploy/native/install.sh --src /path/to/repo --music-dir /srv/music
#
# Опции:
#   --src PATH         исходники репозитория (по умолчанию: текущий каталог)
#   --music-dir PATH   каталог музыкальной библиотеки (по умолчанию /srv/music)
#   --domain NAME      домен для Caddy (по умолчанию music.local)
#   --tls off|internal|acme   режим TLS (по умолчанию off, LAN)
#   --with-ai          установить и включить Ollama (профиль ai)
#   --with-feishin-web собрать веб-клиент Feishin и раздавать его через Caddy
#   --skip-node        не собирать MixWeb (взять готовый dist, если есть)
#   --no-start         не включать и не запускать сервисы

PREFIX="${PREFIX:-/opt/music-stack}"
DATA_DIR="${DATA_DIR:-/var/lib/music-stack}"
CONFIG_DIR="${CONFIG_DIR:-/etc/music-stack}"
LOG_DIR="${LOG_DIR:-/var/log/music-stack}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/music-stack}"
SERVICE_USER="${SERVICE_USER:-music}"
MUSIC_DIR=""
DOMAIN="music.local"
TLS_MODE="off"
WITH_AI=0
WITH_FEISHIN_WEB=0
SKIP_NODE=0
DO_START=1
CADDY_VERSION="2.10.2"
NAVIDROME_VERSION="0.58.0"

usage() { sed -n '2,25p' "$0"; exit 0; }

while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC="$2"; shift 2 ;;
    --music-dir) MUSIC_DIR="$2"; shift 2 ;;
    --domain) DOMAIN="$2"; shift 2 ;;
    --tls) TLS_MODE="$2"; shift 2 ;;
    --with-ai) WITH_AI=1; shift ;;
    --with-feishin-web) WITH_FEISHIN_WEB=1; shift ;;
    --skip-node) SKIP_NODE=1; shift ;;
    --no-start) DO_START=0; shift ;;
    -h|--help) usage ;;
    *) printf 'Неизвестный аргумент: %s\n' "$1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SRC="${SRC:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
MUSIC_DIR="${MUSIC_DIR:-/srv/music}"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Запускать от root: sudo $0 $*"
[ -d "$SRC/mixcore" ] || die "Не найден исходник $SRC/mixcore (укажите --src)"

log "Проверка окружения"
. /etc/os-release 2>/dev/null || true
printf '    дистрибутив: %s %s\n' "${NAME:-неизвестно}" "${VERSION_ID:-?}"
printf '    systemd: %s\n' "$(systemctl --version 2>/dev/null | head -1 || echo нет)"
command -v systemctl >/dev/null || die "systemd обязателен: в WSL включите его в /etc/wsl.conf ([boot] systemd=true) и выполните wsl --shutdown"
[ -d /run/systemd/system ] || die "systemd не запущен. Выполните: sudo wsl --shutdown (из PowerShell) и запустите дистрибутив заново"
command -v curl >/dev/null || die "Нужен curl: sudo apt-get install -y curl"

if ! timeout 10 curl -sSf -o /dev/null https://pypi.org/simple/ 2>/dev/null; then
  warn "pypi.org недоступен. Проверьте сеть/DNS/прокси WSL — установка Python-пакетов не удастся"
  die "Нет доступа к pypi.org. Разрешите выход в интернет или настройте прокси и повторите"
fi

log "Системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip ca-certificates tar gzip jq logrotate >/dev/null
if [ "$SKIP_NODE" -eq 0 ]; then
  apt-get install -y -qq nodejs npm >/dev/null
fi

log "Пользователь сервисов: $SERVICE_USER"
id -u "$SERVICE_USER" >/dev/null 2>&1 || useradd --system --home-dir /srv/music-stack --shell /usr/sbin/nologin "$SERVICE_USER"

log "Каталоги"
install -d -m 0750 "$PREFIX" "$DATA_DIR" "$CONFIG_DIR" "$CONFIG_DIR/secrets" "$CONFIG_DIR/rules" \
  "$LOG_DIR" "$BACKUP_DIR" "$MUSIC_DIR" /srv/music-stack/web /var/log/caddy
install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR/navidrome" "$DATA_DIR/mixcore" "$DATA_DIR/gw"
chown -R "$SERVICE_USER:$SERVICE_USER" "$DATA_DIR"

log "Python-окружение"
python3 -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip wheel
"$PREFIX/venv/bin/pip" install --quiet "$SRC/mixcore" "$SRC/mixgateway"
"$PREFIX/venv/bin/python" -c "import mixcore, mixgateway; print('    mixcore', mixcore.__version__)"

if [ "$SKIP_NODE" -eq 0 ]; then
  log "Сборка MixWeb"
  ( cd "$SRC/mixweb" && npm install --no-audit --no-fund && npm run build )
  rm -rf /srv/music-stack/web/* && cp -r "$SRC/mixweb/dist/." /srv/music-stack/web/
else
  [ -d "$SRC/mixweb/dist" ] || die "Нет $SRC/mixweb/dist: соберите фронтенд заранее или уберите --skip-node"
  rm -rf /srv/music-stack/web/* && cp -r "$SRC/mixweb/dist/." /srv/music-stack/web/
fi
chown -R "$SERVICE_USER:$SERVICE_USER" /srv/music-stack/web
install -d -m 0750 "$PREFIX/deploy/native"
cp -r "$SRC/deploy/native/scripts" "$PREFIX/deploy/native/"
cp -r "$SRC/deploy/native/config" "$PREFIX/deploy/native/"
chmod 0750 "$PREFIX/deploy/native/scripts"/*.sh
cp -r "$SRC/docs" "$PREFIX/" 2>/dev/null || true

log "Navidrome"
if [ ! -x /usr/local/bin/navidrome ]; then
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64) ND_ARCH=amd64 ;;
    aarch64|arm64) ND_ARCH=arm64 ;;
    *) die "Архитектура $ARCH не поддерживается этим установщиком" ;;
  esac
  TMP="$(mktemp -d)"
  curl -fsSL "https://github.com/navidrome/navidrome/releases/download/v${NAVIDROME_VERSION}/navidrome_${NAVIDROME_VERSION}_linux_${ND_ARCH}.tar.gz" -o "$TMP/nd.tgz" \
    || die "Не удалось скачать Navidrome $NAVIDROME_VERSION (проверьте версию на github.com/navidrome/navidrome/releases)"
  tar -xzf "$TMP/nd.tgz" -C "$TMP"
  install -m 0755 "$TMP/navidrome" /usr/local/bin/navidrome
  rm -rf "$TMP"
fi
printf '    %s\n' "$(/usr/local/bin/navidrome --version 2>&1 | head -1)"

log "Caddy"
if [ ! -x /usr/local/bin/caddy ]; then
  ARCH="$(uname -m)"
  case "$ARCH" in
    x86_64) CADDY_ARCH=amd64 ;;
    aarch64|arm64) CADDY_ARCH=arm64 ;;
    *) die "Архитектура $ARCH не поддерживается" ;;
  esac
  curl -fsSL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${CADDY_ARCH}.tar.gz" -o /tmp/caddy.tgz \
    || die "Не удалось скачать Caddy $CADDY_VERSION"
  tar -xzf /tmp/caddy.tgz -C /tmp caddy
  install -m 0755 /tmp/caddy /usr/local/bin/caddy
  rm -f /tmp/caddy /tmp/caddy.tgz
fi
printf '    %s\n' "$(/usr/local/bin/caddy version)"

log "Конфигурация"
sed -e "s|__MUSIC_DIR__|$MUSIC_DIR|g" "$SRC/deploy/native/config/navidrome.env" > "$CONFIG_DIR/navidrome.env"
sed -e "s|__MUSIC_DIR__|$MUSIC_DIR|g" "$SRC/deploy/native/config/mixcore.env.template" > "$CONFIG_DIR/mixcore.env"
sed -e "s|__MUSIC_DIR__|$MUSIC_DIR|g" "$SRC/deploy/native/config/navidrome.toml" > "$CONFIG_DIR/navidrome.toml"
install -m 0640 -o root -g "$SERVICE_USER" "$CONFIG_DIR/navidrome.env" "$CONFIG_DIR/mixcore.env"
install -m 0644 -o root -g "$SERVICE_USER" "$CONFIG_DIR/navidrome.toml"
install -m 0640 -o root -g "$SERVICE_USER" "$SRC/deploy/native/config/Caddyfile" "$CONFIG_DIR/Caddyfile"
install -m 0644 /dev/null "$LOG_DIR/.keep"
install -m 0644 "$SRC/deploy/native/config/logrotate" /etc/logrotate.d/music-stack
printf 'MUSIC_DOMAIN=%s\n' "$DOMAIN" > "$CONFIG_DIR/web.env"
chmod 0640 "$CONFIG_DIR/web.env"

case "$TLS_MODE" in
  off) log "TLS: выключен (LAN, HTTP)" ;;
  internal)
    sed -i 's/^\tauto_https off$/\tauto_https disable_certs/' "$CONFIG_DIR/Caddyfile"
    log "TLS: внутренний CA (сертификат импортировать в Windows)"
    ;;
  acme)
    sed -i 's/^\tauto_https off$/\tauto_https on/' "$CONFIG_DIR/Caddyfile"
    log "TLS: Let's Encrypt (нужен публичный домен и порт 443)"
    ;;
  *) die "Неизвестный --tls: $TLS_MODE" ;;
esac

log "Секреты"
[ -s "$CONFIG_DIR/secrets/navidrome_admin" ] || {
  printf 'mix-admin:%s\n' "$(openssl rand -hex 12)" > "$CONFIG_DIR/secrets/navidrome_admin"
  log "Создан пароль mix-admin (см. $CONFIG_DIR/secrets/navidrome_admin)"
}
[ -s "$CONFIG_DIR/secrets/gateway_token" ] || openssl rand -hex 32 > "$CONFIG_DIR/secrets/gateway_token"
chown root:"$SERVICE_USER" "$CONFIG_DIR/secrets"/* 2>/dev/null || true
chmod 0640 "$CONFIG_DIR/secrets"/*

log "Системные сервисы"
install -m 0644 "$SRC/deploy/systemd/music-navidrome.service" /etc/systemd/system/
install -m 0644 "$SRC/deploy/systemd/mixcore.service" /etc/systemd/system/
install -m 0644 "$SRC/deploy/systemd/mixgateway.service" /etc/systemd/system/
install -m 0644 "$SRC/deploy/systemd/music-web.service" /etc/systemd/system/
install -m 0644 "$SRC/deploy/systemd/music-backup.service" /etc/systemd/system/
install -m 0644 "$SRC/deploy/systemd/music-backup.timer" /etc/systemd/system/
systemctl daemon-reload

log "Инициализация состояния"
runuser -u "$SERVICE_USER" -- env MIX_STATE_DIR="$DATA_DIR/mixcore" \
  "$PREFIX/venv/bin/python" -m mixcore.cli --state-dir "$DATA_DIR/mixcore" init-admin

if [ "$WITH_AI" -eq 1 ]; then
  log "Ollama"
  if ! command -v ollama >/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh >/dev/null
  fi
  install -d -m 0750 -o "$SERVICE_USER" -g "$SERVICE_USER" "$DATA_DIR/ollama"
  cat > /etc/systemd/system/ollama.service <<UNIT
[Unit]
Description=Ollama (локальный ИИ, опционально)
After=network-online.target

[Service]
User=$SERVICE_USER
Group=$SERVICE_USER
Environment=OLLAMA_MODELS=$DATA_DIR/ollama
Environment=OLLAMA_HOST=127.0.0.1:11434
ExecStart=$(command -v ollama)
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable --now ollama.service
  log "Загрузите модель: sudo ollama pull qwen2.5:7b-instruct"
fi

if [ "$WITH_FEISHIN_WEB" -eq 1 ]; then
  log "Сборка веб-клиента Feishin (требуется pnpm, GPL-3.0)"
  if command -v corepack >/dev/null; then corepack enable; fi
  command -v pnpm >/dev/null || npm install -g pnpm
  ( cd "$SRC" && git clone --depth 1 https://github.com/jeffvli/feishin.git /tmp/feishin-src || die "Не удалось клонировать Feishin" )
  ( cd /tmp/feishin-src && pnpm install --prod=false && pnpm run build:web )
  rm -rf /srv/music-stack/web/feishin && mkdir -p /srv/music-stack/web/feishin
  cp -r /tmp/feishin-src/out/web/. /srv/music-stack/web/feishin/
  chown -R "$SERVICE_USER:$SERVICE_USER" /srv/music-stack/web
  log "Feishin (web) доступен по /feishin/"
fi

if [ "$DO_START" -eq 1 ]; then
  log "Запуск сервисов"
  systemctl enable --now music-navidrome.service mixcore.service mixgateway.service music-web.service
  systemctl enable --now music-backup.timer
  log "Ожидание готовности"
  for _ in $(seq 1 60); do
    if curl -fsS http://127.0.0.1:8080/healthz >/dev/null 2>&1; then break; fi
    sleep 2
  done
fi

cat <<EOF

Установка завершена.

Дальше:
  1) Создайте пользователя Navidrome (логин mix-admin из $CONFIG_DIR/secrets/navidrome_admin):
       sudo -u $SERVICE_USER ND_MUSICFOLDER=$MUSIC_DIR ND_DATAFOLDER=$DATA_DIR/navidrome /usr/local/bin/navidrome --createadmin
     Либо через веб-интерфейс при первом запуске.
  2) Положите музыку в $MUSIC_DIR и запустите сканирование:
       sudo -u $SERVICE_USER env ND_DATAFOLDER=$DATA_DIR/navidrome /usr/local/bin/navidrome scan -f
  3) Синхронизируйте библиотеку MixCore и создайте миксы:
       sudo -u $SERVICE_USER env MIX_STATE_DIR=$DATA_DIR/mixcore $PREFIX/venv/bin/python -m mixcore.cli sync-library
       sudo -u $SERVICE_USER env MIX_STATE_DIR=$DATA_DIR/mixcore $PREFIX/venv/bin/python -m mixcore.cli seed --user mix-admin
  4) Проверка состояния: curl http://127.0.0.1:$DOMAIN/healthz  (или http://localhost/healthz)
  5) Feishin подключается к http://<IP-WSL>:$( [ "$TLS_MODE" = off ] && echo 80 || echo 443 )/subsonic

EOF