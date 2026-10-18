import hashlib
import hmac
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.live_dashboard import write_live_dashboard_state
from core.telegram_miniapp import make_miniapp_handler, verify_telegram_init_data


BOT_TOKEN = "123456:TEST_TOKEN"
ALLOWED_USER_ID = "12345"
SECOND_ALLOWED_USER_ID = "8780098092"
ALLOWED_USER_IDS = f"{ALLOWED_USER_ID},{SECOND_ALLOWED_USER_ID}"
ACCESS_PIN = "481726"
NOW = int(time.time())


def signed_init_data(user_id=ALLOWED_USER_ID, auth_date=NOW):
    fields = {
        "auth_date": str(auth_date),
        "query_id": "test-query",
        "user": json.dumps({"id": int(user_id), "is_bot": False}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(
        secret_key, check_string.encode(), hashlib.sha256
    ).hexdigest()
    return urlencode(fields)


class TelegramInitDataTests(unittest.TestCase):
    def test_valid_init_data_returns_authorized_user(self):
        user = verify_telegram_init_data(
            signed_init_data(), BOT_TOKEN, ALLOWED_USER_ID, now=NOW
        )
        self.assertEqual(user["id"], int(ALLOWED_USER_ID))

    def test_rejects_bad_signature(self):
        data = signed_init_data().replace("test-query", "tampered")
        with self.assertRaises(ValueError):
            verify_telegram_init_data(data, BOT_TOKEN, ALLOWED_USER_ID, now=NOW)

    def test_rejects_another_telegram_user(self):
        with self.assertRaisesRegex(ValueError, "not in the allowed Mini App user list"):
            verify_telegram_init_data(
                signed_init_data(user_id="54321"), BOT_TOKEN,
                ALLOWED_USER_IDS, now=NOW,
            )

    def test_accepts_second_authorized_telegram_user(self):
        user = verify_telegram_init_data(
            signed_init_data(user_id=SECOND_ALLOWED_USER_ID),
            BOT_TOKEN, ALLOWED_USER_IDS, now=NOW,
        )
        self.assertEqual(user["id"], int(SECOND_ALLOWED_USER_ID))

    def test_rejects_bot_user(self):
        fields = {
            "auth_date": str(NOW),
            "query_id": "test-query",
            "user": json.dumps({"id": int(ALLOWED_USER_ID), "is_bot": True},
                               separators=(",", ":")),
        }
        check_string = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        fields["hash"] = hmac.new(
            secret_key, check_string.encode(), hashlib.sha256
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "opened as a bot account"):
            verify_telegram_init_data(
                urlencode(fields), BOT_TOKEN, ALLOWED_USER_ID, now=NOW
            )

    def test_rejects_expired_init_data(self):
        with self.assertRaises(ValueError):
            verify_telegram_init_data(
                signed_init_data(auth_date=NOW - 86401), BOT_TOKEN,
                ALLOWED_USER_ID, now=NOW,
            )


class TelegramMiniAppHttpTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_path = os.path.join(self.temp_dir.name, "state.json")
        self.journal_path = os.path.join(self.temp_dir.name, "journal.csv")
        self.pin_path = os.path.join(self.temp_dir.name, ".miniapp-pin.json")
        with open(os.path.join(self.temp_dir.name, "index.html"), "w",
                  encoding="utf-8") as output:
            output.write("Mini App")
        with open(self.state_path, "w", encoding="utf-8") as output:
            json.dump({"broker": "DERIV"}, output)
        with open(self.journal_path, "w", encoding="utf-8", newline="") as output:
            output.write(
                "status,exit_date,entry_date,ticker,strategy,direction,"
                "entry_price,exit_price,exit_reason,pnl\n"
                f"CLOSED,{time.strftime('%Y-%m-%d')},{time.strftime('%Y-%m-%d')},EURUSD,Test,LONG,1.1,1.2,TP,8\n"
            )

        handler = make_miniapp_handler(
            self.temp_dir.name, self.state_path, BOT_TOKEN, ALLOWED_USER_IDS,
            self.journal_path, self.pin_path,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def test_state_requires_telegram_auth_outside_loopback_preview(self):
        with self.assertRaises(HTTPError) as error:
            request = Request(
                f"{self.base_url}/api/state",
                headers={"Host": "miniapp.example"},
            )
            urlopen(request)
        self.assertEqual(error.exception.code, 401)
        error.exception.close()

        invalid_request = Request(
            f"{self.base_url}/api/state",
            headers={"Authorization": "tma invalid"},
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(invalid_request)
        self.assertEqual(error.exception.code, 401)
        self.assertEqual(json.load(error.exception)["reason"], "Malformed initData")
        error.exception.close()

        request = Request(
            f"{self.base_url}/api/pin/status",
            headers={
                "Authorization": f"tma {signed_init_data()}",
            },
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertFalse(json.load(response)["configured"])

        setup_request = Request(
            f"{self.base_url}/api/pin/setup",
            data=json.dumps({"pin": ACCESS_PIN}).encode(),
            headers={
                "Authorization": f"tma {signed_init_data()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(setup_request) as response:
            self.assertTrue(json.load(response)["configured"])
        with open(self.pin_path, encoding="utf-8") as source:
            pin_record = json.load(source)
        self.assertNotIn(ACCESS_PIN, json.dumps(pin_record))

        second_user_request = Request(
            f"{self.base_url}/api/state",
            headers={
                "Authorization": f"tma {signed_init_data(user_id=SECOND_ALLOWED_USER_ID)}",
                "X-MiniApp-PIN": ACCESS_PIN,
            },
        )
        with urlopen(second_user_request) as response:
            self.assertEqual(response.status, 200)
            state = json.load(response)
            self.assertEqual(state["broker"], "DERIV")
            self.assertEqual(state["closed_trades"][0]["exit_reason"], "TP")
            self.assertEqual(state["stats"]["today_pnl"], 8)

        wrong_password_request = Request(
            f"{self.base_url}/api/state",
            headers={
                "Authorization": f"tma {signed_init_data()}",
                "X-MiniApp-PIN": "000000",
            },
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(wrong_password_request)
        self.assertEqual(error.exception.code, 403)
        self.assertEqual(json.load(error.exception)["error"], "Code PIN incorrect")
        error.exception.close()

        unauthorized_setup = Request(
            f"{self.base_url}/api/pin/setup",
            data=json.dumps({"pin": "000000"}).encode(),
            headers={
                "Authorization": f"tma {signed_init_data(user_id='54321')}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(unauthorized_setup)
        self.assertEqual(error.exception.code, 401)
        error.exception.close()

    def test_state_allows_read_only_loopback_preview(self):
        request = Request(f"{self.base_url}/api/state")
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 428)
        error.exception.close()

        setup_request = Request(
            f"{self.base_url}/api/pin/setup",
            data=json.dumps({"pin": ACCESS_PIN}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(setup_request) as response:
            self.assertTrue(json.load(response)["configured"])

        request = Request(
            f"{self.base_url}/api/state",
            headers={"X-MiniApp-PIN": ACCESS_PIN},
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(json.load(response)["broker"], "DERIV")

    def test_existing_pin_can_only_be_changed_with_current_pin(self):
        first_setup = Request(
            f"{self.base_url}/api/pin/setup",
            data=json.dumps({"pin": ACCESS_PIN}).encode(),
            headers={
                "Authorization": f"tma {signed_init_data()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(first_setup):
            pass

        rejected_change = Request(
            f"{self.base_url}/api/pin/setup",
            data=json.dumps({"pin": "123456", "current_pin": "000000"}).encode(),
            headers={
                "Authorization": f"tma {signed_init_data()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(rejected_change)
        self.assertEqual(error.exception.code, 403)
        error.exception.close()

        change = Request(
            f"{self.base_url}/api/pin/setup",
            data=json.dumps({"pin": "123456", "current_pin": ACCESS_PIN}).encode(),
            headers={
                "Authorization": f"tma {signed_init_data()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(change) as response:
            self.assertTrue(json.load(response)["configured"])

    def test_pin_attempts_are_rate_limited_after_five_failures(self):
        setup_request = Request(
            f"{self.base_url}/api/pin/setup",
            data=json.dumps({"pin": ACCESS_PIN}).encode(),
            headers={
                "Authorization": f"tma {signed_init_data()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urlopen(setup_request):
            pass

        for _ in range(5):
            wrong_request = Request(
                f"{self.base_url}/api/state",
                headers={
                    "Authorization": f"tma {signed_init_data()}",
                    "X-MiniApp-PIN": "000000",
                },
            )
            with self.assertRaises(HTTPError) as error:
                urlopen(wrong_request)
            error.exception.close()

        correct_request = Request(
            f"{self.base_url}/api/state",
            headers={
                "Authorization": f"tma {signed_init_data()}",
                "X-MiniApp-PIN": ACCESS_PIN,
            },
        )
        with self.assertRaises(HTTPError) as error:
            urlopen(correct_request)
        self.assertEqual(error.exception.code, 429)
        self.assertGreater(json.load(error.exception)["retry_after"], 0)
        error.exception.close()

    def test_static_files_are_served_and_other_paths_are_not(self):
        with urlopen(f"{self.base_url}/") as response:
            self.assertEqual(response.read().decode(), "Mini App")
        with self.assertRaises(HTTPError) as error:
            urlopen(f"{self.base_url}/../state.json")
        self.assertEqual(error.exception.code, 404)
        error.exception.close()


class DashboardStateTests(unittest.TestCase):
    def test_state_export_is_compact_and_json_safe(self):
        class Position:
            ticket = 7
            symbol = "EURUSD"
            type = "buy"
            volume = 0.1
            open_price = 1.1
            current_price = 1.2
            stop_loss = 1.0
            take_profit = 1.3
            profit = 10

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            write_live_dashboard_state(
                path, "DERIV", "DEMO", {"equity": 1010, "balance": 1000},
                [Position()], [
                    {"status": "CLOSED", "ticker": "EURUSD", "pnl": 8,
                     "exit_date": time.strftime("%Y-%m-%d"),
                     "direction": "LONG", "entry_price": 1.1,
                     "exit_price": 1.2, "exit_reason": "TP"},
                    {"status": "OPEN", "ticker": "GBPUSD", "pnl": 0},
                ],
                {"nb_trades": 1, "win_rate": 100, "profit_factor": float("inf"),
                 "net_pnl": 8},
                "OK", ["EURUSD"], info={
                    "risk": 1.0, "daily_drawdown_pct": 1.2,
                    "daily_limit_pct": 3.0,
                }, activity=["trade clôturé"], connections={"bot": True, "mt5": True},
            )
            with open(path, encoding="utf-8") as source:
                state = json.load(source)

        self.assertEqual(state["positions"][0]["ticket"], 7)
        self.assertEqual(len(state["closed_trades"]), 1)
        self.assertIsNone(state["stats"]["profit_factor"])
        self.assertEqual(state["stats"]["today_pnl"], 8)
        self.assertEqual(state["closed_trades"][0]["direction"], "LONG")
        self.assertEqual(state["closed_trades"][0]["exit_reason"], "TP")
        self.assertEqual(state["connections"], {"bot": True, "mt5": True})
        self.assertEqual(state["info"]["daily_drawdown_pct"], "1.2")
        self.assertEqual(state["activity"], ["trade clôturé"])
        self.assertNotIn("bot_token", state)


if __name__ == "__main__":
    unittest.main()
