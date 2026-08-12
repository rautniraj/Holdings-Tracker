import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_NTFY_SERVER = "https://ntfy.sh"


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _int_env(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got: {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got: {value}")
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
    trade_history_sleep_seconds: int
    reuse_access_token: bool
    ntfy_topic: str | None
    ntfy_server: str

    @classmethod
    def from_env(cls) -> "Settings":
        ntfy_topic = os.getenv("NTFY_TOPIC", "").strip() or None
        ntfy_server = os.getenv("NTFY_SERVER", DEFAULT_NTFY_SERVER).strip() or DEFAULT_NTFY_SERVER
        return cls(
            client_id=_required("DHAN_CLIENT_ID"),
            pin=_required("DHAN_PIN"),
            totp_secret=_required("DHAN_TOTP_SECRET"),
            max_retries=_int_env("DHAN_MAX_RETRIES", 5),
            auth_max_retries=_int_env("DHAN_AUTH_MAX_RETRIES", 5),
            trade_from=os.getenv("DHAN_TRADE_FROM", "").strip() or None,
            trade_to=os.getenv("DHAN_TRADE_TO", "").strip() or None,
            database_url=os.getenv("DATABASE_URL", "").strip() or None,
            trade_history_sleep_seconds=_int_env(
                "DHAN_TRADE_HISTORY_SLEEP_SECONDS", 1, minimum=0
            ),
            reuse_access_token=os.getenv("DHAN_REUSE_ACCESS_TOKEN", "false").strip().lower()
            in {"1", "true", "yes", "on"},
            ntfy_topic=ntfy_topic,
            ntfy_server=ntfy_server,
        )
