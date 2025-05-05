from typing import Any, Dict, Optional


class MessageFactory:
    """
    Factory for generating message dictionaries with a specified type and sender.
    """

    def __init__(self, message_type: str, from_id: str, *args: Any, **kwargs: Any) -> None:
        """
        Initialize the MessageFactory.

        Args:
            message_type (str): The type of the message.
            from_id (str): The identifier of the sender.
            *args (Any): Additional positional arguments (unused).
            **kwargs (Any): Additional keyword arguments to include in the message.
        """
        self.message_type = message_type
        self.from_id = from_id
        self.args = args
        self.kwargs = kwargs

    def generate_message(self, text: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a message dictionary.

        Args:
            text (Optional[str]): Optional text to include in the message.

        Returns:
            Dict[str, Any]: A dictionary containing the message data.
        """
        # Base message with type and sender.
        message: Dict[str, Any] = {
            "type": self.message_type,
            "from_id": self.from_id,
        }
        # Optionally include text if provided.
        if text is not None:
            message["text"] = text
        # Merge in any additional keyword arguments.
        message.update(self.kwargs)
        return message
