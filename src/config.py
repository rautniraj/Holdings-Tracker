import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got: {raw!r}") from exc
    if value < 1:
        raise ValueError(f"{name} must be at least 1, got: {value}")
    return value


@dataclass(frozen=True)
class Settings:
    client_id: str
    pin: str
    totp_secret: str
    max_retries: int
    auth_max_retries: int
    trade_from: str | None
    trade_to: str | None
    database_url: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            client_id=_required("DHAN_CLIENT_ID"),
            pin=_required("DHAN_PIN"),
            totp_secret=_required("DHAN_TOTP_SECRET"),
            max_retries=_int_env("DHAN_MAX_RETRIES", 10),
            auth_max_retries=_int_env("DHAN_AUTH_MAX_RETRIES", 10),
            trade_from=os.getenv("DHAN_TRADE_FROM", "").strip() or None,
            trade_to=os.getenv("DHAN_TRADE_TO", "").strip() or None,
            database_url=os.getenv("DATABASE_URL", "").strip() or None,
        )
