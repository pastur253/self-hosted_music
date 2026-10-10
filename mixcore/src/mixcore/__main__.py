from __future__ import annotations

import uvicorn

from .api.app import create_app
from .config import Settings

app = create_app()


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "mixcore.asgi:app",
        host="0.0.0.0",
        port=8080,
        log_level=settings.log_level.lower(),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()