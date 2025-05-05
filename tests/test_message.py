import unittest
from AIConnector.common.message import MessageTypes


class TestMessageTypes(unittest.TestCase):
    def test_message_types_values(self):
        self.assertEqual(MessageTypes.HELLO.value, "hello")
        self.assertEqual(MessageTypes.TEXT.value, "text")
        self.assertEqual(MessageTypes.SYSTEM_MESSAGE.value, "system_message")
        self.assertEqual(MessageTypes.HEARTBEAT.value, "heartbeat")
        self.assertEqual(MessageTypes.FINAL_MESSAGE.value, "final_message")
        self.assertEqual(MessageTypes.ERROR.value, "error")
        self.assertEqual(MessageTypes.JOB_LIST.value, "job_list")
