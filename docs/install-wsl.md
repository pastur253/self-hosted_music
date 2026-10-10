# Развёртывание в WSL без Docker

Инструкция устанавливает MusicStack нативно: Navidrome и Caddy — готовые бинарники,
MixCore и MixGateway — Python-пакеты в venv под systemd, MixWeb — статическая сборка,
которую раздаёт Caddy. Docker не используется.

Артефакты установки лежат в `deploy/native/` (install.sh, конфиги, скрипты) и
`deploy/systemd/` (юниты). Скрипт установки их же копирует в `/opt/music-stack/deploy/native/`.

---

## 0. Что проверено, а что нет

| Проверено в этой среде (WSL Ubuntu 26.04.1, systemd 259) | Не проверено |
|---|---|
| Синтаксис `install.sh` и всех скриптов (`bash -n`) | Фактическая установка пакетов из PyPI и бинарников с GitHub — в этой среде нет доступа к сети |
| `systemd-analyze verify` для всех 6 юнитов — синтаксис и структура корректны | Фактический старт сервисов, права и hardening в runtime |
| Подстановка `__MUSIC_DIR__` в env-шаблоны | Реальные HTTP-ответы Navidrome и MixCore |
| Синтаксис всех 45 Python-файлов проекта | Сборка MixWeb (`npm run build`) — Node в WSL не установлен |
| Доступность tz-базы (`zoneinfo` работает) | Feishin web-сборка |

> **Важно:** ядро этой машины сообщает `6.18.40.1-microsoft-standard-WSL2`. Если у вас
> WSL другой версии, проверьте шаг 1 — остальные шаги не зависят от версии ядра,
> только от включённого systemd.

---

## 1. Включить systemd в WSL

WSL не загружает systemd по умолчанию.

```bash
sudo tee /etc/wsl.conf >/dev/null <<'EOF'
[boot]
systemd=true

[user]
default=ВАШ_ЛИНУКС_ПОЛЬЗОВАТЕЛЬ
EOF
```

Из PowerShell:

```powershell
wsl --shutdown
```

Запустите дистрибутив заново и убедитесь:

```bash
systemctl is-system-running        # ожидается: running | degraded
ls /run/systemd/system            # каталог существует
```

Если `degraded` — посмотрите, что именно: `systemctl --failed`.

## 2. Проверить сеть внутри WSL

```bash
curl -sSf -o /dev/null -w '%{http_code}\n' https://pypi.org/simple/
curl -sSf -o /dev/null -w '%{http_code}\n' https://github.com
```

Если недоступно — установщик прервётся с понятной ошибкой. Типовые причины и решения:

| Симптом | Решение |
|---|---|
| DNS не резолвит | Проверьте `/etc/resolv.conf`; в корпоративной сети задайте DNS в `/etc/wsl.conf`: `[network] generateResolvConf=false` и свой `resolv.conf` |
| Прямой выход закрыт, есть прокси | `export https_proxy=http://user:pass@proxy:3128` и то же в `/etc/environment`, `apt` — `Acquire::http::Proxy` |
| Всё работает только в Windows | В WSL2 обычно доступен нативный выход. Если используется VPN/файрвол Windows, добавьте правило для `vmmemWSL` |

## 3. Положить репозиторий в WSL

Инструкция использует исходники. Можно оставить репозиторий на диске Windows —
установка это допускает, но **музыкальную библиотеку в WSL так держать нельзя**
(см. шаг 4).

```bash
sudo apt-get update && sudo apt-get install -y git
git clone <url-репозитория> ~/music-stack
cd ~/music-stack
```

Либо скопируйте уже существующую папку:

```powershell
wsl -d Ubuntu -- cp -r "/mnt/d/Ilya/PetProjects/Self-hosted Music" ~/music-stack
```

## 4. Музыкальная библиотека — только в файловой системе WSL

Navidrome сканирует и отдаёт файлы. Каталог на `/mnt/c`, `/mnt/d` (DrvFs) даёт
кратно худшую производительность на больших библиотеках из-за трансляции ввода-вывода.

```bash
sudo mkdir -p /srv/music
sudo chown music:music /srv/music
# если библиотека уже в Windows:
cp -r "/mnt/d/Ilya/Music" /srv/music/ && sudo chown -R music:music /srv/music
```

Проверка после копирования:

```bash
du -sh /srv/music
sudo -u music find /srv/music -type f | wc -l
```

Если библиотеку нужно держать на большом внешнем диске, см. раздел 11.

## 5. Установка

```bash
cd ~/music-stack
sudo ./deploy/native/install.sh \
  --src ~/music-stack \
  --music-dir /srv/music \
  --domain music.local \
  --tls off
```

Опции:

| Опция | Назначение |
|---|---|
| `--src PATH` | Путь к исходникам (по умолчанию — каталог скрипта) |
| `--music-dir PATH` | Каталог библиотеки (по умолчанию `/srv/music`) |
| `--domain NAME` | Домен для Caddy (по умолчанию `music.local`) |
| `--tls off\|internal\|acme` | Режим TLS, подробности в разделе 8 |
| `--with-ai` | Поставить Ollama и включить сервис (потом `ollama pull qwen2.5:7b-instruct`) |
| `--with-feishin-web` | Собрать веб-клиент Feishin из исходников (нужны `pnpm` и сеть) |
| `--skip-node` | Не ставить Node и не собирать MixWeb (использовать готовый `mixweb/dist`) |
| `--no-start` | Установить, но не запускать сервисы |

Что делает установщик:

1. Проверяет root, systemd и доступ к pypi.org.
2. Ставит `python3-venv`, `python3-pip`, `jq`, `nodejs`, `npm` (если не `--skip-node`).
3. Создаёт системного пользователя `music` и каталоги:
   `/opt/music-stack` (код и venv), `/var/lib/music-stack/{navidrome,mixcore,gw}`,
   `/etc/music-stack` (конфиги и секреты), `/var/log/music-stack`, `/var/backups/music-stack`,
   `/srv/music-stack/web` (статика MixWeb).
4. Создаёт venv и ставит `mixcore` и `mixgateway` из исходников.
5. Собирает MixWeb и раскладывает в `/srv/music-stack/web`.
6. Скачивает Navidrome и Caddy в `/usr/local/bin`.
7. Кладёт конфиги в `/etc/music-stack`, генерирует секреты.
8. Ставит 6 systemd-юнитов и включает их.
9. Инициализирует каталог состояния MixCore (`init-admin`).

Скрипт идемпотентен: повторный запуск обновляет конфиги и перезапускает сервисы,
данные и секреты не трогает.

## 6. Первый запуск Navidrome и пользователи

```bash
# создать администратора (логин mix-admin, пароль из секрета)
sudo -u music env \
  ND_DATAFOLDER=/var/lib/music-stack/navidrome \
  ND_MUSICFOLDER=/srv/music \
  ND_CONFIGFILE=/etc/music-stack/navidrome.toml \
  /usr/local/bin/navidrome --createadmin

# посмотреть сгенерированный пароль
sudo cat /etc/music-stack/secrets/navidrome_admin
```

Затем первую синхронизацию библиотеки:

```bash
sudo -u music env \
  ND_DATAFOLDER=/var/lib/music-stack/navidrome \
  ND_MUSICFOLDER=/srv/music \
  ND_CONFIGFILE=/etc/music-stack/navidrome.toml \
  /usr/local/bin/navidrome scan -f
```

Обычных пользователей (кроме `mix-admin`) создайте в веб-интерфейсе Navidrome
(`http://<адрес>:4533`) или через CLI `navidrome user create`. Их учётные данные
MixCore не хранит: он работает от сервисной учётной записи, права держит в своём
реестре (ADR-003).

## 7. Миксы и синтезы

```bash
STATE=/var/lib/music-stack/mixcore
VENV=/opt/music-stack/venv/bin

sudo -u music env MIX_STATE_DIR=$STATE $VENV/python -m mixcore.cli sync-library
sudo -u music env MIX_STATE_DIR=$STATE $VENV/python -m mixcore.cli rebuild-profile --user mix-admin
sudo -u music env MIX_STATE_DIR=$STATE $VENV/python -m mixcore.cli seed --user mix-admin --dry-run
sudo -u music env MIX_STATE_DIR=$STATE $VENV/python -m mixcore.cli seed --user mix-admin
```

Полезно: `templates` (каталог синтезов), `generate --mix-id mix-admin:daily_mix`,
`selftest`.

## 8. TLS

Значение `--tls` на этапе установки:

| Режим | Что получится | Когда применять |
|---|---|---|
| `off` (по умолчанию) | HTTP на порту 80 | Доверенная домашняя сеть |
| `internal` | HTTPS с сертификатом внутреннего CA | Нужен HTTPS без интернета; сертификат один раз импортируется в Windows |
| `acme` | Let's Encrypt | Публичный домен и входящий 443/tcp |

Переключение уже установленной системы:

```bash
sudo sed -i 's/^\tauto_https off$/\tauto_https disable_certs/' /etc/music-stack/Caddyfile
sudo systemctl restart music-web.service
sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt   # импортировать в Windows
```

В `Caddyfile` есть закомментированные варианты — правьте его вручную, если нужны
другие параметры.

## 9. Feishin без Docker

Три варианта:

1. **Настольное приложение (рекомендуется).** Скачайте Feishin для Windows и
   подключите к `http://<IP-WSL>/subsonic` (тип сервера — Subsonic). Docker не нужен.
2. **Веб-сборка Feishin в этом же стеке.** `sudo ./deploy/native/install.sh --with-feishin-web`
   (нужны `pnpm` и доступ к GitHub; лицензия GPL-3.0). Открывается по `/feishin/`.
3. **Использовать только MixWeb.** В нём есть всё, чего нет в Feishin: real-time
   совместные плейлисты, объяснения, редактирование правил.

> Ограничение из ТЗ (FE-L02): push-обновлений внутри Feishin нет — содержимое
> плейлиста обновляется при открытии. Миксы при этом видны как обычные плейлисты.

## 10. Доступ из Windows и других устройств

- Из WSL: `http://localhost/` (работает через localhostForwarding).
- Из Windows по IP WSL: `ip -4 addr show eth0 | grep inet` → обычно `172.x.x.x`,
  страница `http://172.x.x.x/`.
- Из других устройств локальной сети: адрес IP хоста Windows или проброс
  `netsh interface portproxy`. Пример для HTTP:

```powershell
netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=80 connectaddress=<IP-WSL>
```

Убедитесь, что брандмауэр Windows разрешает порт и что `Caddy` слушает `0.0.0.0:80`
(в конфиге это поведение по умолчанию).

## 11. Автозапуск

WSL не «загружается» как обычная ОС: дистрибутив запускается только когда вы в него
вошли или когда кто-то выполнил `wsl -d Ubuntu`. Варианты:

**Вариант A — задача Windows по входу в систему:**

```powershell
$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument "-d Ubuntu -- /opt/music-stack/deploy/native/scripts/autostart.sh"
$trigger = New-ScheduledTaskTrigger -AtLogOn
Register-ScheduledTask -TaskName "MusicStack" -Action $action -Trigger $trigger -RunLevel Highest
```

**Вариант B — держать дистрибутив живым** (если нужен постоянный доступ по сети):

```bash
sudo tee /etc/systemd/system/wsl-keepalive.service >/dev/null <<'EOF'
[Unit]
Description=Keep WSL running for MusicStack

[Service]
Type=oneshot
ExecStart=/bin/sleep infinity
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl enable --now wsl-keepalive.service
```

Ограничение: при выключении компьютера или `wsl --shutdown` стек останавливается;
после старта Windows нужен один из вариантов выше.

## 12. Резервное копирование

Таймер уже включён (ежедневно в 04:30 UTC со случайным сдвигом):

```bash
systemctl list-timers music-backup.timer
sudo systemctl start music-backup.service      # выполнить сейчас
sudo /opt/music-stack/deploy/native/scripts/verify-restore-native.sh
```

Состав бэкапа: `navidrome backup`, состояние MixCore, `/etc/music-stack`
(включая секреты; архив закрыт правами root, храните его вне хоста).

Восстановление:

```bash
sudo systemctl stop mixcore.service mixgateway.service music-navidrome.service
sudo tar -xzf /var/backups/music-stack/backup-<stamp>.tar.gz -C /tmp/restore
sudo rsync -a --delete /tmp/restore/mixcore/mixcore/ /var/lib/music-stack/mixcore/
sudo tar -xzf /tmp/restore/mixcore/navidrome/backup/navidrome_backup.tar.gz -C /var/lib/music-stack/navidrome
sudo chown -R music:music /var/lib/music-stack
sudo systemctl start music-navidrome.service mixcore.service mixgateway.service
```

## 13. Обновление

```bash
sudo /opt/music-stack/deploy/native/scripts/backup-native.sh
cd ~/music-stack && git pull
sudo ./deploy/native/install.sh --src ~/music-stack --music-dir /srv/music --tls off
sudo -u music env MIX_STATE_DIR=/var/lib/music-stack/mixcore \
  /opt/music-stack/venv/bin/python -m mixcore.cli migrate
sudo systemctl restart mixcore.service mixgateway.service music-web.service
curl -fsS http://127.0.0.1:8080/healthz | jq .effective_mode
```

Откат: восстановить `/var/lib/music-stack/mixcore` из бэкапа и вернуть прежний
код через `git checkout <commit>` с повторным запуском установщика.

## 14. Удаление

```bash
sudo systemctl disable --now music-navidrome.service mixcore.service mixgateway.service music-web.service music-backup.timer
sudo rm -f /etc/systemd/system/music-navidrome.service /etc/systemd/system/mixcore.service \
  /etc/systemd/system/mixgateway.service /etc/systemd/system/music-web.service \
  /etc/systemd/system/music-backup.{service,timer}
sudo systemctl daemon-reload
sudo rm -rf /opt/music-stack /etc/music-stack /var/lib/music-stack /var/log/music-stack
# данные и бэкапы удаляйте вручную, если они больше не нужны
```

## 15. Диагностика

| Симптом | Проверка | Причина |
|---|---|---|
| `MusicStack недоступен` | `curl -fsS http://127.0.0.1:8080/healthz` | MixCore не поднялся; `journalctl -u mixcore -n 50` |
| MixCore стартует и падает | `journalctl -u mixcore | grep -i lock` | «Каталог состояния занят» — запущен второй инстанс (AC-N13) |
| Navidrome не стартует | `journalctl -u music-navidrome -n 50` | Проверьте права `music` на `/srv/music` и `/var/lib/music-stack/navidrome` |
| Миксы пустые | `journalctl -u mixcore | grep sync-library` | Не выполнен `sync-library` или пустая библиотека |
| Feishin не подключается | `curl 'http://127.0.0.1/subsonic/rest/ping.view?u=t&p=t&v=1.16.1&c=t&f=json'` | Проверьте `music-web.service` и `MIX_DOMAIN` в `/etc/music-stack/web.env` |
| MixWeb отдаёт 404 | `ls /srv/music-stack/web/index.html` | Не собран фронтенд: уберите `--skip-node` и переустановите |
| Нет realtime | — | Ограничение FE-L02: realtime работает только в MixWeb |
| Медленное сканирование | Библиотека на `/mnt/*` | Перенесите в `/srv/music` (раздел 4) |

Общие команды:

```bash
systemctl status music-navidrome mixcore mixgateway music-web
journalctl -u mixcore -f
curl -fsS http://127.0.0.1:8080/healthz | jq
sudo -u music env MIX_STATE_DIR=/var/lib/music-stack/mixcore /opt/music-stack/venv/bin/python -m mixcore.cli selftest
```

## 16. Что осталось непроверенным

- `apt`, `pip` и `curl` в этой среде не имели сети, поэтому фактическая установка
  пакетов и бинарников не выполнялась. Первый запуск на машине с интернетом —
  это и есть проверка шага 5.
- События (NFR-P01–P13), health-check и поток WebSocket проверяются после старта:
  команда `selftest` и `/healthz` показывают работоспособность, а нагрузочные
  пороги из ТЗ требуют отдельного прогона на реальной библиотеке.