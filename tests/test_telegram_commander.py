import unittest
from unittest.mock import patch

from core.telegram_commander import TelegramCommand, TelegramCommander
from core.notifier import TelegramNotifier


class TelegramCommanderOwnerTests(unittest.TestCase):
    primary_id = "12345"
    second_id = "8780098092"

    def setUp(self):
        self.commander = TelegramCommander(
            "test-token", self.primary_id, enabled=True,
            owner_ids=self.second_id,
        )

    def private_message(self, chat_id, sender_id=None):
        return {
            "message": {
                "chat": {"id": int(chat_id), "type": "private"},
                "from": {"id": int(sender_id or chat_id)},
                "text": "/statut",
            }
        }

    def test_both_private_owner_chats_are_authorized(self):
        self.assertTrue(self.commander._is_authorized(
            self.private_message(self.primary_id)
        ))
        self.assertTrue(self.commander._is_authorized(
            self.private_message(self.second_id)
        ))

    def test_rejects_non_owner_and_non_private_messages(self):
        self.assertFalse(self.commander._is_authorized(
            self.private_message("98765")
        ))
        group_message = self.private_message(self.second_id)
        group_message["message"]["chat"]["type"] = "group"
        self.assertFalse(self.commander._is_authorized(group_message))
        mismatched_sender = self.private_message(
            self.second_id, sender_id=self.primary_id
        )
        self.assertFalse(self.commander._is_authorized(mismatched_sender))

    def test_queued_command_keeps_originating_owner_chat(self):
        self.commander._q.put(TelegramCommand("/pause", self.second_id))
        self.assertEqual(
            self.commander.drain(),
            [TelegramCommand("/pause", self.second_id)],
        )

    @patch("core.telegram_commander.send_message", return_value=(True, ""))
    def test_command_reply_returns_to_originating_chat(self, send_message):
        self.commander.reply("Bot en pause", chat_id=self.second_id)
        self.assertEqual(send_message.call_args.kwargs["chat_id"], self.second_id)

    @patch("core.notifier.send_message", return_value=(True, ""))
    def test_bot_notifications_are_sent_to_both_owners(self, send_message):
        notifier = TelegramNotifier(
            "test-token", self.primary_id, enabled=True, owner_ids=self.second_id
        )
        self.assertTrue(notifier.send("Trade ouvert", parse_mode=None))
        self.assertEqual(
            [call.kwargs["chat_id"] for call in send_message.call_args_list],
            [self.primary_id, self.second_id],
        )

    @patch("core.telegram_commander.send_message", return_value=(True, ""))
    def test_reply_cannot_be_routed_to_non_owner_chat(self, send_message):
        self.assertFalse(self.commander.reply("Test", chat_id="98765"))
        send_message.assert_not_called()

    @patch("core.telegram_commander.send_message", return_value=(True, ""))
    def test_shared_reply_reaches_both_owner_chats(self, send_message):
        self.assertTrue(self.commander.reply_all("Bot démarré", keyboard=True))
        self.assertEqual(
            [call.kwargs["chat_id"] for call in send_message.call_args_list],
            [self.primary_id, self.second_id],
        )


if __name__ == "__main__":
    unittest.main()
