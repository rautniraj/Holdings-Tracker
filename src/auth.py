import requests
import pyotp

from src.config import Settings
from src.retry import with_retries

AUTH_URL = "https://auth.dhan.co/app/generateAccessToken"


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
