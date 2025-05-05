import unittest
from AIConnector.core.chat_client import MessageFactory


class TestMessageFactory(unittest.TestCase):
    def test_generate_message_with_text(self):
        mf = MessageFactory(message_type="text", from_id="test_id", extra="value")
        msg = mf.generate_message("Hello")
        self.assertEqual(msg["type"], "text")
        self.assertEqual(msg["from_id"], "test_id")
        self.assertEqual(msg["text"], "Hello")
        self.assertEqual(msg["extra"], "value")
