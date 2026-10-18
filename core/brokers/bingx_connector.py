"""
Connecteur BingX — Spot Trading
════════════════════════════════

Documentation officielle : https://bingx-api.github.io/docs/
Base URL                 : https://open-api.bingx.com
Authentification         : header X-BX-APIKEY + signature HMAC-SHA256
                            calculée sur la query string triée, avec un
                            paramètre `timestamp` (ms) et `recvWindow`.

⚠️ IMPORTANT
- Ce module n'a pas pu être testé contre l'API réelle (pas d'accès réseau
  dans cet environnement). Avant tout usage en argent réel, valider CHAQUE
  endpoint avec de petits montants et logger les réponses brutes.
- Toujours démarrer avec `mode="paper"` (aucune requête d'écriture envoyée).
- Ne jamais committer de vraies clés API — utiliser des variables
  d'environnement (voir .env.example).
"""

import hashlib
import hmac
import time
import requests
from urllib.parse import urlencode
from dataclasses import dataclass
from typing import Optional


BASE_URL = "https://open-api.bingx.com"


@dataclass
class BingXOrder:
    symbol: str
    side: str          # "BUY" ou "SELL"
    order_type: str     # "MARKET" ou "LIMIT"
    quantity: float
    price: Optional[float] = None


class BingXConnector:
    """
    Client REST BingX Spot.

    mode="paper"  -> aucune requête réelle envoyée ; les ordres sont
                     simulés localement et journalisés (voir core/journal.py).
    mode="live"   -> requêtes réelles envoyées à l'API BingX.
    """

    def __init__(self, api_key: str, api_secret: str, mode: str = "paper",
                 recv_window: int = 5000, timeout: int = 10):
        if mode not in ("paper", "live"):
            raise ValueError("mode doit être 'paper' ou 'live'")
        self.api_key = api_key
        self.api_secret = api_secret
        self.mode = mode
        self.recv_window = recv_window
        self.timeout = timeout
        self._session = requests.Session()
        self._paper_balance = {"USDT": 10_000.0}
        self._paper_orders = []

    # ── Signature ──────────────────────────────────────────────────
    def _sign(self, params: dict) -> str:
        query = urlencode(sorted(params.items()))
        return hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _headers(self) -> dict:
        return {"X-BX-APIKEY": self.api_key}

    def _request(self, method: str, path: str, params: dict = None,
                 signed: bool = False):
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = self.recv_window
            params["signature"] = self._sign(params)

        url = f"{BASE_URL}{path}"
        try:
            if method == "GET":
                resp = self._session.get(url, params=params,
                                          headers=self._headers(),
                                          timeout=self.timeout)
            else:
                resp = self._session.post(url, params=params,
                                           headers=self._headers(),
                                           timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            return {"error": str(e)}

    # ── Données de marché (publiques, pas besoin de clé) ────────────
    def get_ticker_24h(self, symbol: str) -> dict:
        """symbol au format BingX, ex: 'BTC-USDT'."""
        return self._request("GET", "/openApi/spot/v1/ticker/24hr",
                              {"symbol": symbol})

    def get_klines(self, symbol: str, interval: str = "5m", limit: int = 200) -> dict:
        """interval: 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M"""
        return self._request("GET", "/openApi/spot/v1/market/kline", {
            "symbol": symbol, "interval": interval, "limit": limit,
        })

    def get_order_book(self, symbol: str, limit: int = 20) -> dict:
        return self._request("GET", "/openApi/spot/v1/market/depth",
                              {"symbol": symbol, "limit": limit})

    # ── Compte (privé, signé) ────────────────────────────────────
    def get_balance(self) -> dict:
        if self.mode == "paper":
            return {"mode": "paper", "balances": self._paper_balance}
        return self._request("GET", "/openApi/spot/v1/account/balance",
                              signed=True)

    # ── Trading ──────────────────────────────────────────────────
    def place_order(self, order: BingXOrder) -> dict:
        if self.mode == "paper":
            simulated = {
                "mode": "paper",
                "symbol": order.symbol,
                "side": order.side,
                "type": order.order_type,
                "quantity": order.quantity,
                "price": order.price,
                "status": "SIMULATED_FILLED",
                "timestamp": int(time.time() * 1000),
            }
            self._paper_orders.append(simulated)
            return simulated

        # Mode réel — désactivé tant que la clé/secret ne sont pas
        # confirmées et testées manuellement. Retirer cette garde
        # explicitement (en connaissance de cause) pour activer.
        params = {
            "symbol": order.symbol,
            "side": order.side,
            "type": order.order_type,
            "quantity": order.quantity,
        }
        if order.order_type == "LIMIT" and order.price:
            params["price"] = order.price
        return self._request("POST", "/openApi/spot/v1/trade/order",
                              params, signed=True)

    def get_paper_orders(self) -> list:
        return list(self._paper_orders)
