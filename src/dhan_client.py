from datetime import date, timedelta

import requests

from src.config import Settings
from src.retry import with_retries

API_BASE = "https://api.dhan.co/v2"


class DhanClient:
    def __init__(self, access_token: str, settings: Settings) -> None:
        self._settings = settings
        self._session = requests.Session()
        self._session.headers.update(
            {
                "access-token": access_token,
                "Accept": "application/json",
            }
        )

    def _get(self, path: str) -> requests.Response:
        def _request() -> requests.Response:
            response = self._session.get(f"{API_BASE}{path}", timeout=30)
            response.raise_for_status()
            return response

        return with_retries(
            _request,
            max_attempts=self._settings.max_retries,
            label=f"GET {path}",
        )

    def get_profile(self) -> dict:
        return self._get("/profile").json()

    def get_holdings(self) -> list:
        payload = self._get("/holdings").json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Expected holdings list, got: {type(payload).__name__}")
        return payload

    def get_trade_history(
        self,
        from_date: str,
        to_date: str,
    ) -> tuple[list[dict], int]:
        page = 0
        all_trades: list[dict] = []

        while True:
            path = f"/trades/{from_date}/{to_date}/{page}"
            payload = self._get(path).json()

            if not isinstance(payload, list):
                raise RuntimeError(
                    f"Expected trade history list on page {page}, got: {type(payload).__name__}"
                )

            if not payload:
                break

            all_trades.extend(payload)
            page += 1

        return all_trades, page


def default_trade_date_range(settings: Settings) -> tuple[str, str]:
    if settings.trade_from and settings.trade_to:
        return settings.trade_from, settings.trade_to

    today = date.today()
    from_date = today - timedelta(days=30)
    return from_date.isoformat(), today.isoformat()
