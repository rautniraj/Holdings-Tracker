from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def with_retries(
    operation: Callable[[], T],
    *,
    max_attempts: int,
    label: str,
) -> T:
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            print(f"[retry] {label} attempt {attempt}/{max_attempts} failed: {exc}")

    raise RuntimeError(
        f"{label} failed after {max_attempts} attempts"
    ) from last_error
