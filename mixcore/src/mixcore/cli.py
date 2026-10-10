from __future__ import annotations

import asyncio
import json
import secrets
from argparse import ArgumentParser
from typing import Any

from .config import Settings
from .domain.models import MixDefinition, UserSettings
from .domain.templates import all_specs
from .runtime import build_runtime, configure_logging, run_selftest
from .storage.layout import Layout


def _settings(args: Any) -> Settings:
    env = {
        "MIX_STATE_DIR": args.state_dir,
        "MIX_NAVIDROME_URL": args.navidrome_url,
        "MIX_NAVIDROME_USER": args.navidrome_user,
        "MIX_SYNTH_MODE": args.synth_mode,
        "MIX_LOG_LEVEL": args.log_level,
    }
    return Settings.from_env(env)


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="mixcore", description="MixCore CLI")
    parser.add_argument("--state-dir", default="./data/mixcore")
    parser.add_argument("--navidrome-url", default="http://127.0.0.1:4533")
    parser.add_argument("--navidrome-user", default="mix-admin")
    parser.add_argument("--synth-mode", default="algo", choices=["algo", "hybrid", "ai"])
    parser.add_argument("--log-level", default="INFO")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-admin", help="Подготовить каталог состояния и первого администратора")
    sub.add_parser("migrate", help="Применить миграции файловой схемы состояния")
    sub.add_parser("selftest", help="Проверка готовности: Navidrome, lock, режим генерации")
    sub.add_parser("templates", help="Показать каталог синтезов")

    sync = sub.add_parser("sync-library", help="Синхронизировать кэш метаданных из Navidrome")
    sync.add_argument("--full", action="store_true")

    seed = sub.add_parser("seed", help="Создать демо-миксы и сгенерировать их")
    seed.add_argument("--user", default="admin")
    seed.add_argument("--timezone", default="UTC")
    seed.add_argument("--dry-run", action="store_true")

    rebuild = sub.add_parser("rebuild-profile", help="Пересчитать профиль вкуса")
    rebuild.add_argument("--user", required=True)

    gen = sub.add_parser("generate", help="Сгенерировать один микс")
    gen.add_argument("--mix-id", required=True)
    gen.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = _settings(args)
    configure_logging(args.log_level)
    handler = {
        "init-admin": cmd_init_admin,
        "migrate": cmd_migrate,
        "selftest": cmd_selftest,
        "templates": cmd_templates,
        "sync-library": cmd_sync_library,
        "seed": cmd_seed,
        "rebuild-profile": cmd_rebuild_profile,
        "generate": cmd_generate,
    }[args.command]
    return handler(args, settings)


def cmd_init_admin(args: Any, settings: Settings) -> int:
    layout = Layout.create(settings.state_dir)
    stored = layout.schema.check()
    layout.synth_templates.save({"templates": [spec.to_dict() for spec in all_specs()], "updated_at": 0.0})
    layout.users.ensure(
        {
            "admin": UserSettings(user_id="admin", timezone="UTC", role="admin").to_dict(),
        }
    )
    api_keys = layout.api_keys.load() or {}
    if not api_keys:
        key = secrets.token_hex(32)
        import hashlib

        api_keys = {hashlib.sha256(key.encode()).hexdigest()[:32]: {"scope": "admin", "owner": "admin"}}
        layout.api_keys.save(api_keys)
        print(f"Создан API-ключ: {key}")
    print(f"Каталог состояния: {layout.root} (схема {stored if stored is not None else layout.schema.current})")
    return 0


def cmd_migrate(args: Any, settings: Settings) -> int:
    layout = Layout.create(settings.state_dir)
    pending = layout.schema.migrations_available()
    if not pending:
        print(f"Миграции не требуются (схема {layout.schema.read()})")
        return 0
    layout.schema.write(layout.schema.current)
    print(f"Применены миграции: {pending} → {layout.schema.current}")
    return 0


def cmd_templates(args: Any, settings: Settings) -> int:
    for spec in all_specs():
        print(f"{spec.code:22} {spec.name_ru:22} len={spec.length:<3} period={spec.period}")
    return 0


def cmd_selftest(args: Any, settings: Settings) -> int:
    async def run() -> dict[str, Any]:
        runtime = await build_runtime(settings, with_scheduler=False)
        try:
            return await run_selftest(runtime)
        finally:
            await runtime.aclose()
            runtime.lock.release()

    result = asyncio.run(run())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_sync_library(args: Any, settings: Settings) -> int:
    async def run() -> dict[str, Any]:
        runtime = await build_runtime(settings, with_scheduler=False)
        try:
            stats = await runtime.library.sync(full=args.full)
            return {"total": stats.total, "duration_hours": stats.duration_hours}
        finally:
            await runtime.aclose()
            runtime.lock.release()

    print(json.dumps(asyncio.run(run()), ensure_ascii=False))
    return 0


def cmd_seed(args: Any, settings: Settings) -> int:
    async def run() -> list[dict[str, Any]]:
        runtime = await build_runtime(settings, with_scheduler=False)
        try:
            user = runtime.mixes.save_user(
                UserSettings(user_id=args.user, timezone=args.timezone, role="user", navidrome_username=args.user)
            )
            del user
            results = []
            for spec in all_specs():
                if spec.code == "weekly_digest":
                    continue
                mix = MixDefinition(
                    mix_id=f"{args.user}:{spec.code}",
                    name=spec.name_ru,
                    owner_id=args.user,
                    template_code=spec.code,
                    length=spec.length,
                    schedule="4:0" if spec.period == "weekly" else "",
                )
                runtime.layout.mix(mix.mix_id).save(mix.to_dict())
                outcome = await runtime.mixes.generate(mix, dry_run=args.dry_run)
                results.append(
                    {
                        "mix_id": outcome.mix_id,
                        "title": outcome.title,
                        "tracks": len(outcome.track_ids),
                        "mode": outcome.mode,
                        "metrics": outcome.metrics,
                        "problems": outcome.quality_problems,
                    }
                )
            return results
        finally:
            await runtime.aclose()
            runtime.lock.release()

    results = asyncio.run(run())
    for item in results:
        print(json.dumps(item, ensure_ascii=False))
    return 0


def cmd_rebuild_profile(args: Any, settings: Settings) -> int:
    async def run() -> dict[str, Any]:
        runtime = await build_runtime(settings, with_scheduler=False)
        try:
            profile = runtime.mixes.rebuild_profile(args.user)
            return {
                "user": profile.user_id,
                "plays": profile.total_plays,
                "tracks": len(profile.stats),
                "genres": len(profile.genre_weights),
                "artists": len(profile.artist_weights),
            }
        finally:
            await runtime.aclose()
            runtime.lock.release()

    print(json.dumps(asyncio.run(run()), ensure_ascii=False))
    return 0


def cmd_generate(args: Any, settings: Settings) -> int:
    async def run() -> dict[str, Any]:
        runtime = await build_runtime(settings, with_scheduler=False)
        try:
            raw = runtime.layout.mix(args.mix_id).load()
            if raw is None:
                raise SystemExit(f"Микс {args.mix_id} не найден")
            outcome = await runtime.mixes.generate(MixDefinition.from_dict(raw), dry_run=args.dry_run)
            return {
                "mix_id": outcome.mix_id,
                "title": outcome.title,
                "track_count": len(outcome.track_ids),
                "mode": outcome.mode,
                "metrics": outcome.metrics,
                "problems": outcome.quality_problems,
                "written": outcome.written,
            }
        finally:
            await runtime.aclose()
            runtime.lock.release()

    print(json.dumps(asyncio.run(run()), ensure_ascii=False, indent=2))
    return 0


def entrypoint() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    entrypoint()