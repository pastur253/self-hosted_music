# Self-hosted музыкальный сервис (Navidrome + Feishin + MixCore)

Плейлисты-синтезы, миксы по времени суток и погоде,
совместные плейлисты с реальным временем, гибридные рекомендации
(алгоритмический базовый режим + опциональный локальный ИИ).

## Состав

| Компонент | Стек | Роль |
|---|---|---|
| `navidrome` | Go | Библиотека, пользователи, аннотации, плейлисты (Subsonic API) |
| `mixcore` | Python 3.12, FastAPI | Ядро: профили, скоринг, синтезы, совместные плейлисты, расписание, real-time |
| `mixgateway` | Python 3.12, FastAPI, httpx | Subsonic BFF: прокси, наблюдение событий, редиректы аудио |
| `mixweb` | TypeScript, React, Vite | PWA: каталог синтезов, миксы, совместные плейлисты, состояние |
| `feishin` | готовое приложение | Клиент, подключается к шлюзу |
| `caddy` | Go | TLS и маршрутизация |
| `ollama` | опционально | Локальный ИИ (профиль `ai`) |

Отдельной СУБД нет: состояние MixCore — файлы в томе `mix_data`
(`state/`, `logs/`, `cache/`, `vectors/`, `lock`).

## Быстрый старт

### Без Docker (WSL, systemd)

```bash
sudo ./deploy/native/install.sh --src ~/music-stack --music-dir /srv/music --tls off
```

Полная инструкция: `docs/install-wsl.md`.

### Docker Compose

```bash
cd deploy
./scripts/bootstrap.sh
```

Далее по подсказкам скрипта: создать пользователей Navidrome, положить учётные
данные в `deploy/secrets/navidrome_admin`, синхронизировать библиотеку, создать миксы.

Ручная последовательность:

```bash
cd deploy
cp .env.example .env            # проверьте PUBLIC_DOMAIN, MUSIC_PATH
mkdir -p secrets
printf '%s' 'логин:пароль' > secrets/navidrome_admin && chmod 600 secrets/navidrome_admin
openssl rand -hex 32 > secrets/gateway_token && chmod 600 secrets/gateway_token

docker compose build
docker compose up -d
docker compose exec mixcore python -m mixcore.cli --state-dir /var/lib/mixcore init-admin
docker compose exec mixcore python -m mixcore.cli --state-dir /var/lib/mixcore sync-library
docker compose exec mixcore python -m mixcore.cli --state-dir /var/lib/mixcore seed --user alice
```

Точки входа:

| Что | Адрес |
|---|---|
| MixWeb | `http://<домен>/` |
| MixCore API | `http://<домен>/api/v1/...` |
| Subsonic (для Feishin) | `http://<домен>/subsonic` |
| Feishin (браузер) | `http://<хост>:9180` (профиль `client`) |
| Состояние | `http://<домен>/healthz` |

## Подключение Feishin

В Docker-версии Feishin адрес и тип сервера задаются переменными
(`SERVER_TYPE=subsonic`, `SERVER_URL=http://<домен>/subsonic`, `SERVER_LOCK=true`).
В настольном приложении: «Manage servers → Add server» → тип `Subsonic`, адрес
`http://<домен>/subsonic`.

Сгенерированные миксы и синтезы видны как обычные плейлисты Navidrome.
Обновление содержимого происходит при открытии плейлиста — push-обновлений
внутри Feishin нет.

## Режимы генерации

| Режим | Флаг | Поведение |
|---|---|---|
| `algo` (по умолчанию) | `MIX_SYNTH_MODE=algo` | Только алгоритмы: кандидаты → фильтры → скоринг → разнообразие → дедупликация |
| `hybrid` | `MIX_SYNTH_MODE=hybrid` + `MIX_LLM_ENABLED=true` | Алгоритмы + ИИ с лимитом влияния `MIX_LLM_MAX_INFLUENCE` |
| `ai` | `MIX_SYNTH_MODE=ai` | Максимум ИИ; авто-откат в `hybrid`, если модуль недоступен |

Режим `algo` не требует ИИ, внешних агентов и сети. При сбое любого ИИ-модуля
система остаётся в `algo`, фиксирует причину в `mix_runs` и показывает её в MixWeb.

## Каталог синтезов

`discover_weekly`, `daily_mix`, `weather_mix`, `energy`, `calm_morning`,
`night_drive`, `retro_cohort`, `release_radar`, `forgotten_favorites`,
`loved_only`, `weekly_digest`.

```bash
docker compose exec mixcore python -m mixcore.cli templates
```

## Разработка и тесты

```bash
cd mixcore
python -m pytest tests -q          # 18 тестов: хранилище, домен, инварианты
python -m ruff check src tests
```

Проверяемые инварианты: атомарная запись файлов, advisory-lock единственного
писателя, детерминированность генерации при фиксированном seed, независимость
результата от ИИ при нулевом влиянии, фильтры «не повторять» и шаблонов.

## Документация

- `TZ.md` — техническое задание с ограничениями стека и критериями приёмки
- `docs/install-wsl.md` — **развёртывание в WSL без Docker** (systemd, бинарники, venv)
- `docs/runbook.md` — эксплуатация, бэкап, восстановление, обновление
- `docs/adr/` — архитектурные решения