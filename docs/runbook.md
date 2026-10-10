# Runbook

## Состав стека

| Сервис | Роль | Том |
|---|---|---|
| `caddy` | TLS, маршрутизация | `caddy_data` |
| `navidrome` | Библиотека и Subsonic API | `./data/navidrome` |
| `mixcore` | Ядро, API, WebSocket, расписание | `mix_data` |
| `mixgateway` | Прокси Subsonic для Feishin | без тома |
| `mixweb` | PWA | без тома |
| `feishin` | Клиент (профиль `client`) | — |
| `ollama` | Локальный ИИ (профиль `ai`) | `ollama_data` |

Наружу открыты только 80/443 (Caddy) и 127.0.0.1:9180 (Feishin, если включён).
Сеть `app` помечена `internal: true`.

## Ежедневные операции

```bash
cd deploy
docker compose ps
docker compose logs -f mixcore
docker compose exec mixcore python -m mixcore.cli --state-dir /var/lib/mixcore selftest
```

## Бэкап

```bash
cd deploy
./scripts/backup.sh
```

Состав: `navidrome backup` (CLI), снимок тома `mix_data`, каталог `config/`,
шаблон `.env`. Проверка архива выполняется внутри скрипта.

## Восстановление

1. Остановить сервисы: `docker compose down`
2. Восстановить данные Navidrome из `backups/backup-*/navidrome/backup/` согласно
   процедуре Navidrome (файл БД положить в `./data/navidrome/`).
3. Восстановить состояние MixCore:

```bash
docker run --rm -v "${COMPOSE_PROJECT_NAME:-self-hosted-music}_mix_data:/dst" \
  -v "$PWD/backups:/backup:ro" alpine:3.20 \
  sh -c 'rm -rf /dst/* && cd /dst && tar xf /backup/backup-*/mixcore_state/.'
```

4. Поднять стек: `docker compose up -d`
5. Проверить: `docker compose exec mixcore python -m mixcore.cli --state-dir /var/lib/mixcore selftest`
   и открыть MixWeb → «Состояние».

Проверка бэкапа без развёртывания: `./scripts/verify-restore.sh`.

## Обновление

1. `./scripts/backup.sh`
2. Зафиксировать новые теги версий в `.env` (NFR-M02).
3. `docker compose pull && docker compose up -d`
4. `docker compose exec mixcore python -m mixcore.cli --state-dir /var/lib/mixcore migrate`
5. `docker compose exec mixcore python -m mixcore.cli --state-dir /var/lib/mixcore selftest`

Откат: вернуть прежние теги и восстановить том `mix_data` из бэкапа.

## Диагностика

| Симптом | Проверка | Причина и решение |
|---|---|---|
| MixWeb не открывается | `docker compose logs caddy mixweb` | Проверить маршрут `/` → `mixweb:8080` |
| Feishin не подключается | `curl http://<домен>/subsonic/rest/ping.view?u=test&p=x&v=1.16.1&c=t&f=json` | Шлюз недоступен или неверный `SERVER_URL` |
| Миксы не генерируются | `docker compose logs mixcore`, `healthz` | Navidrome недоступен или каталог `state/mixes` пуст |
| Пустой каталог синтезов | `mixcore ... sync-library` | Не синхронизирован кэш `cache/track_meta.json.gz` |
| «Каталог состояния занят» | `docker compose ps` | Запущен второй MixCore; лишний инстанс остановить (AC-N13) |
| Нет плейлистов миксов в Feishin | `GET /api/v1/mixes` | Микс создан, но не сгенерирован: `POST /api/v1/mixes/{id}/generate` |
| Нет realtime в Feishin | — | Ограничение FE-L02: Feishin не получает push-события; realtime работает в MixWeb |

## Ручные операции

```bash
# Каталог синтезов
docker compose exec mixcore python -m mixcore.cli templates

# Создать миксы и сразу сгенерировать (dry-run ничего не пишет в Navidrome)
docker compose exec mixcore python -m mixcore.cli seed --user alice --dry-run

# Пересчёт профиля вкуса после импорта истории
docker compose exec mixcore python -m mixcore.cli rebuild-profile --user alice

# Перегенерация одного микса
docker compose exec mixcore python -m mixcore.cli generate --mix-id alice:daily_mix --dry-run
```

## Удаление и пересборка кэша

Каталог `cache/` внутри тома `mix_data` пересобираем: его можно удалить целиком,
MixCore восстановит метаданные из Navidrome (AC-N11).

```bash
docker compose stop mixcore
docker run --rm -v "${COMPOSE_PROJECT_NAME:-self-hosted-music}_mix_data:/data" \
  alpine:3.20 sh -c 'rm -rf /data/cache/*'
docker compose start mixcore
```

Каталог `state/` не пересобирается — это конфигурация и права. Восстанавливается
только из бэкапа.

## Включение локального ИИ

```bash
docker compose --profile ai up -d
docker compose exec ollama ollama pull qwen2.5:7b-instruct
# в .env: MIX_LLM_ENABLED=true, MIX_SYNTH_MODE=hybrid, MIX_LLM_MAX_INFLUENCE=0.2
```

При недоступном Ollama система останется в `algo` и укажет причину в MixWeb →
«Состояние» и в `GET /healthz` (поле `degraded_reason`).