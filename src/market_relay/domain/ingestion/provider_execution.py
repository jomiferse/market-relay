"""Hard wall-clock isolation for synchronous provider calls.

Provider code runs in a short-lived process. A non-cooperative call is
terminated at the deadline, unlike a thread which Python cannot safely stop.
The supported deployment target is POSIX/Linux and uses `fork`; provider
methods must not use inherited database sessions.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable
from typing import Any, cast


class ProviderTimeoutError(Exception):
    """Provider work exceeded its configured hard deadline."""


class ProviderProcessError(Exception):
    """Provider work failed in isolation; raw child details are discarded."""


def _invoke(send: Any, action: Callable[[], object]) -> None:
    try:
        send.send((True, action()))
    except BaseException:  # noqa: BLE001 - discard untrusted child details
        send.send((False, None))
    finally:
        send.close()


def run_with_deadline[T](action: Callable[[], T], *, timeout_seconds: float) -> T:
    """Run provider-only work in a killable child and return its result."""

    try:
        context = multiprocessing.get_context("fork")
    except ValueError as exc:  # pragma: no cover - production target is Linux
        raise RuntimeError("Hard provider deadlines require a POSIX fork context.") from exc

    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_invoke, args=(send, action), daemon=True)
    process.start()
    send.close()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(1)
        if process.is_alive():  # pragma: no cover - SIGTERM normally suffices
            process.kill()
            process.join()
        receive.close()
        raise ProviderTimeoutError("provider_deadline_exceeded")

    if not receive.poll():
        receive.close()
        raise ProviderProcessError("provider_process_failed")
    succeeded, value = receive.recv()
    receive.close()
    if not succeeded:
        raise ProviderProcessError("provider_process_failed")
    return cast("T", value)
