"""HTTP API entry point."""

from __future__ import annotations

import uvicorn

from market_relay.api.app import create_app

app = create_app()


def run() -> None:
    uvicorn.run("market_relay.entrypoints.api:app", host="0.0.0.0", port=8000)  # noqa: S104


if __name__ == "__main__":
    run()
