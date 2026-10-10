#!/usr/bin/env bash
set -euo pipefail
#
# Запуск MusicStack после старта дистрибутива WSL.
# Положите в /etc/systemd/system/music-stack-autostart.service:
#   ExecStart=/opt/music-stack/deploy/native/scripts/autostart.sh
#
# Либо используйте этот скрипт вручную: bash autostart.sh

systemctl start music-navidrome.service mixcore.service mixgateway.service music-web.service
printf 'MusicStack запущен\n'