from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pyotp
import requests

from src.config import Settings
from src.retry import with_retries

AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"
PROFILE_URL = "https://api.dhan.co/v2/profile"
AUTH_RESPONSE_PATH = Path(__file__).resolve().parents[1] / "output" / "auth_response.json"
TOKEN_EXPIRY_BUFFER = timedelta(minutes=5)


def generate_totp(secret: str) -> str:
    return pyotp.TOTP(secret).now()


def generate_access_token(settings: Settings) -> dict:
    def _authenticate() -> dict:
        totp = generate_totp(settings.totp_secret)
        response = requests.post(
            AUTH_URL,
            params={
                "dhanClientId": settings.client_id,
                "pin": settings.pin,
                "totp": totp,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()

        access_token = payload.get("accessToken")
        if not access_token:
            raise RuntimeError(
                f"Authentication succeeded but accessToken missing: {payload}"
            )

        return payload

    return with_retries(
        _authenticate,
        max_attempts=settings.auth_max_retries,
        label="Dhan authentication",
    )


def load_cached_token() -> dict | None:
    if not AUTH_RESPONSE_PATH.is_file():
        return None

    try:
        payload = json.loads(AUTH_RESPONSE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    if not isinstance(payload, dict) or not payload.get("accessToken"):
        return None

    return payload


def save_cached_token(payload: dict) -> None:
    AUTH_RESPONSE_PATH.parent.mkdir(exist_ok=True)
    AUTH_RESPONSE_PATH.write_text(
        json.dumps(payload, indent=2, default=str),
        encoding="utf-8",
    )


def parse_expiry_time(value: str) -> datetime:
    return datetime.fromisoformat(value.strip())


def is_token_expired(
    expiry_time: str,
    *,
    buffer: timedelta = TOKEN_EXPIRY_BUFFER,
) -> bool:
    try:
        expiry = parse_expiry_time(expiry_time)
    except ValueError:
        return True

    return datetime.now() >= expiry - buffer


def validate_access_token(access_token: str) -> bool:
    try:
        response = requests.get(
            PROFILE_URL,
            headers={
                "access-token": access_token,
                "Accept": "application/json",
            },
            timeout=30,
        )
        return response.status_code == 200
    except requests.RequestException:
        return False


def get_access_token(settings: Settings) -> tuple[dict, bool]:
    if settings.reuse_access_token:
        cached = load_cached_token()
        if cached:
            expiry_time = cached.get("expiryTime")
            access_token = cached.get("accessToken")
            if (
                isinstance(access_token, str)
                and isinstance(expiry_time, str)
                and not is_token_expired(expiry_time)
                and validate_access_token(access_token)
            ):
                return cached, True

    payload = generate_access_token(settings)

    if settings.reuse_access_token:
        save_cached_token(payload)

    return payload, False
