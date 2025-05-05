from enum import Enum


class MessageTypes(Enum):
    """
    Enum representing different types of messages exchanged between peers.
    """
    HELLO = "hello"
    TEXT = "text"
    SYSTEM_MESSAGE = "system_message"
    HEARTBEAT = "heartbeat"
    FINAL_MESSAGE = "final_message"
    ERROR = "error"
    JOB_LIST = "job_list"
