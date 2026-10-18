"""HTTPS-proxy-friendly server helpers for the read-only Telegram Mini App."""
from __future__ import annotations

import csv
import hashlib
import hmac
import json
import logging
import math
import os
import re
import secrets
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qsl, urlsplit

from core.miniapp_commands import enqueue

logger = logging.getLogger(__name__)


def verify_telegram_init_data(init_data: str, bot_token: str,
                              expected_user_id: str, now: int | None = None,
                              max_age_seconds: int = 86400) -> dict:
    """Validate Telegram Web App initData and return its authorized user."""
    if not init_data or len(init_data) > 8192:
        raise ValueError("Invalid initData length")

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True,
                          max_num_fields=50)
    except ValueError as exc:
        raise ValueError("Malformed initData") from exc
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("Duplicate initData fields")

    fields = dict(pairs)
    received_hash = fields.pop("hash", "")
    if len(received_hash) != 64:
        raise ValueError("Missing initData hash")

    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"),
                          hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, check_string.encode("utf-8"),
                             hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        raise ValueError("Invalid initData signature")

    try:
        auth_date = int(fields["auth_date"])
        user = json.loads(fields["user"])
        current_time = int(time.time()) if now is None else int(now)
        user_id = str(user["id"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid initData user or auth date") from exc

    if auth_date > current_time + 60 or current_time - auth_date > max_age_seconds:
        raise ValueError("Expired initData")
    if not isinstance(user, dict):
        raise ValueError("Invalid Telegram user data")
    if user.get("is_bot"):
        raise ValueError("Mini App was opened as a bot account")
    allowed_user_ids = {
        user_id.strip() for user_id in str(expected_user_id).split(",")
        if user_id.strip()
    }
    if user_id not in allowed_user_ids:
        raise ValueError("Telegram user is not in the allowed Mini App user list")
    return user


def make_miniapp_handler(static_dir: str, state_file: str,
                         bot_token: str, allowed_user_ids: str,
                         journal_file: str = "", pin_file: str = "",
                         command_file: str = "", allowed_origin: str = ""):
    pin_path = pin_file or os.path.join(os.path.dirname(state_file), ".telegram_miniapp_pin.json")
    failed_pin_attempts = {}
    attempt_lock = threading.Lock()
    pin_lockout_after = 5
    pin_lockout_seconds = 15 * 60

    static_files = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/index.html": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/style.css": ("style.css", "text/css; charset=utf-8"),
    }

    class TelegramMiniAppHandler(BaseHTTPRequestHandler):
        def log_message(self, _format, *_args):
            return

        def _respond(self, status: int, body: bytes,
                     content_type: str = "application/json; charset=utf-8"):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            origin = self.headers.get("Origin", "").rstrip("/")
            if allowed_origin and origin == allowed_origin.rstrip("/"):
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self):
            origin = self.headers.get("Origin", "").rstrip("/")
            if not allowed_origin or origin != allowed_origin.rstrip("/"):
                self._respond(403, b'{"error":"Origin not allowed"}')
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-MiniApp-PIN")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def _authorized_user(self):
            authorization = self.headers.get("Authorization", "")
            host = self.headers.get("Host", "").lower()
            local_hosts = {
                "localhost", f"localhost:{self.server.server_port}",
                "127.0.0.1", f"127.0.0.1:{self.server.server_port}",
            }
            local_preview = (
                self.client_address[0] in {"127.0.0.1", "::1"}
                and host in local_hosts
            )
            if local_preview and not authorization:
                logger.info("Serving read-only Mini App preview over loopback")
                return "local-preview"
            if not authorization.startswith("tma "):
                self._respond(401, b'{"error":"Telegram authorization required"}')
                return None
            try:
                user = verify_telegram_init_data(
                    authorization[4:], bot_token, allowed_user_ids
                )
            except ValueError as exc:
                logger.warning("Mini App Telegram authorization rejected: %s", exc)
                body = json.dumps(
                    {"error": "Telegram authorization rejected", "reason": str(exc)},
                    ensure_ascii=True,
                ).encode("utf-8")
                self._respond(401, body)
                return None
            return str(user["id"])

        def _read_pin_record(self):
            try:
                with open(pin_path, "r", encoding="utf-8") as source:
                    record = json.load(source)
            except FileNotFoundError:
                return None
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                logger.error("Mini App PIN configuration could not be read: %s", exc)
                self._respond(503, b'{"error":"PIN configuration could not be read"}')
                return False
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("salt"), str)
                or not isinstance(record.get("hash"), str)
                or not re.fullmatch(r"[0-9a-f]{32}", record["salt"])
                or not re.fullmatch(r"[0-9a-f]{64}", record["hash"])
            ):
                logger.error("Mini App PIN configuration is malformed")
                self._respond(503, b'{"error":"PIN configuration is invalid"}')
                return False
            return record

        def _pin_is_valid(self, user_id, record, pin):
            now = time.monotonic()
            with attempt_lock:
                failures, blocked_until = failed_pin_attempts.get(user_id, (0, 0))
                if blocked_until > now:
                    retry_after = int(blocked_until - now) + 1
                    body = json.dumps({
                        "error": "Trop de tentatives. Réessaie plus tard.",
                        "retry_after": retry_after,
                    }).encode("utf-8")
                    self._respond(429, body)
                    return False
                if blocked_until:
                    failed_pin_attempts.pop(user_id, None)

            candidate = hashlib.pbkdf2_hmac(
                "sha256", pin.encode("utf-8"), bytes.fromhex(record["salt"]),
                310_000,
            ).hex()
            if hmac.compare_digest(candidate, record["hash"]):
                with attempt_lock:
                    failed_pin_attempts.pop(user_id, None)
                return True

            with attempt_lock:
                failures, _ = failed_pin_attempts.get(user_id, (0, 0))
                failures += 1
                blocked_until = (
                    now + pin_lockout_seconds if failures >= pin_lockout_after else 0
                )
                failed_pin_attempts[user_id] = (failures, blocked_until)
                retry_after = max(0, int(blocked_until - now) + 1)
            body = json.dumps({
                "error": "Code PIN incorrect",
                "retry_after": retry_after,
            }).encode("utf-8")
            self._respond(429 if retry_after else 403, body)
            return False

        def _save_pin_record(self, pin):
            salt = secrets.token_bytes(16)
            record = {
                "salt": salt.hex(),
                "hash": hashlib.pbkdf2_hmac(
                    "sha256", pin.encode("utf-8"), salt, 310_000
                ).hex(),
            }
            directory = os.path.dirname(os.path.abspath(pin_path))
            os.makedirs(directory, exist_ok=True)
            fd, temporary_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as output:
                    json.dump(record, output)
                os.replace(temporary_path, pin_path)
            except OSError:
                if os.path.exists(temporary_path):
                    os.remove(temporary_path)
                raise

        def do_GET(self):
            path = urlsplit(self.path).path
            if path == "/api/pin/status":
                if self._authorized_user() is None:
                    return
                record = self._read_pin_record()
                if record is False:
                    return
                body = json.dumps({"configured": record is not None}).encode("utf-8")
                self._respond(200, body)
                return
            if path == "/api/state":
                self._send_state()
                return

            asset = static_files.get(path)
            if asset is None:
                self._respond(404, b"Not found", "text/plain; charset=utf-8")
                return
            filename, content_type = asset
            try:
                with open(os.path.join(static_dir, filename), "rb") as source:
                    body = source.read()
            except OSError:
                self._respond(500, b"Mini App asset unavailable",
                              "text/plain; charset=utf-8")
                return
            self._respond(200, body, content_type)

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == "/api/control":
                self._control()
                return
            if path != "/api/pin/setup":
                self._respond(404, b"Not found", "text/plain; charset=utf-8")
                return
            user_id = self._authorized_user()
            if user_id is None:
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length < 1 or content_length > 1024:
                    raise ValueError("Invalid request size")
                payload = json.loads(self.rfile.read(content_length))
            except (ValueError, UnicodeError, json.JSONDecodeError):
                self._respond(400, b'{"error":"Invalid PIN request"}')
                return
            if not isinstance(payload, dict):
                self._respond(400, b'{"error":"Invalid PIN request"}')
                return
            pin = payload.get("pin")
            if not isinstance(pin, str) or not re.fullmatch(r"\d{6}", pin):
                self._respond(400, b'{"error":"Le PIN doit contenir exactement 6 chiffres"}')
                return
            record = self._read_pin_record()
            if record is False:
                return
            if record is not None:
                current_pin = payload.get("current_pin")
                if not isinstance(current_pin, str) or not re.fullmatch(r"\d{6}", current_pin):
                    self._respond(400, b'{"error":"Le PIN actuel est obligatoire"}')
                    return
                if not self._pin_is_valid(user_id, record, current_pin):
                    return
            try:
                self._save_pin_record(pin)
            except OSError as exc:
                logger.error("Mini App PIN configuration could not be saved: %s", exc)
                self._respond(503, b'{"error":"PIN could not be saved"}')
                return
            body = json.dumps({"configured": True}).encode("utf-8")
            self._respond(200, body)

        def _control(self):
            user_id = self._authorized_user()
            if user_id is None:
                return
            record = self._read_pin_record()
            if record is False:
                return
            if record is None:
                self._respond(428, b'{"error":"PIN setup required"}')
                return
            supplied_pin = self.headers.get("X-MiniApp-PIN", "")
            if not re.fullmatch(r"\d{6}", supplied_pin) or not self._pin_is_valid(user_id, record, supplied_pin):
                if re.fullmatch(r"\d{6}", supplied_pin):
                    return
                self._respond(403, b'{"error":"PIN required"}')
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                action = payload.get("action") if isinstance(payload, dict) else None
            except (ValueError, UnicodeError, json.JSONDecodeError):
                action = None
            if action not in {"pause", "resume"}:
                self._respond(400, b'{"error":"Unsupported control action"}')
                return
            if not command_file:
                self._respond(503, b'{"error":"Control channel is not configured"}')
                return
            try:
                enqueue(command_file, action, user_id)
            except OSError:
                self._respond(503, b'{"error":"Control command could not be queued"}')
                return
            self._respond(202, json.dumps({"queued": action}).encode("utf-8"))

        def _send_state(self):
            user_id = self._authorized_user()
            if user_id is None:
                return
            record = self._read_pin_record()
            if record is False:
                return
            if record is None:
                self._respond(428, b'{"error":"PIN setup required"}')
                return
            supplied_pin = self.headers.get("X-MiniApp-PIN", "")
            if not re.fullmatch(r"\d{6}", supplied_pin):
                self._respond(403, b'{"error":"PIN required"}')
                return
            if not self._pin_is_valid(user_id, record, supplied_pin):
                return

            try:
                with open(state_file, "rb") as source:
                    state = json.load(source)
            except FileNotFoundError:
                self._respond(503, b'{"error":"Bot state is not available yet"}')
                return
            except (OSError, json.JSONDecodeError):
                self._respond(503, b'{"error":"Bot state could not be read"}')
                return
            if journal_file and os.path.isfile(journal_file):
                try:
                    with open(
                        journal_file, "r", newline="", encoding="utf-8-sig"
                    ) as source:
                        rows = [
                            row for row in csv.DictReader(source)
                            if row.get("status") == "CLOSED"
                        ]
                    def number(value):
                        try:
                            result = float(value or 0)
                        except (TypeError, ValueError):
                            return None
                        return result if math.isfinite(result) else None

                    state["closed_trades"] = [
                        {
                            "date": str(row.get("exit_date") or row.get("entry_date") or ""),
                            "symbol": str(row.get("ticker") or ""),
                            "strategy": str(row.get("strategy") or ""),
                            "direction": str(row.get("direction") or ""),
                            "entry_date": str(row.get("entry_date") or ""),
                            "entry_price": number(row.get("entry_price")),
                            "exit_price": number(row.get("exit_price")),
                            "exit_reason": str(row.get("exit_reason") or ""),
                            "pnl": number(row.get("pnl")),
                        }
                        for row in rows[-90:]
                    ]
                    today = time.strftime("%Y-%m-%d")
                    if not isinstance(state.get("stats"), dict):
                        state["stats"] = {}
                    state["stats"]["today_pnl"] = sum(
                        number(row.get("pnl")) or 0
                        for row in rows
                        if str(row.get("exit_date") or row.get("entry_date") or "")[:10] == today
                    )
                except (OSError, UnicodeError, csv.Error) as exc:
                    logger.warning("Mini App journal could not be read: %s", exc)
                    self._respond(503, b'{"error":"Trade history could not be read"}')
                    return
            body = json.dumps(state, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._respond(200, body)

    return TelegramMiniAppHandler
