import asyncio
from datetime import datetime
from typing import Any, Optional


class Job:
    """
    Represents a job with associated data, peer information, and an optional asyncio task.
    """

    def __init__(self, job_id: str, data: Any, peer_id: str, queue_id: str) -> None:
        """
        Initialize a new Job instance.

        Args:
            job_id (str): Unique identifier for the job.
            data (Any): Data associated with the job.
            peer_id (str): Identifier of the peer related to the job.
            queue_id (str): Identifier for the job queue.
        """
        self.job_id: str = job_id
        self.data: Any = data
        self.peer_id: str = peer_id
        self.queue_id: str = queue_id
        self.start_heartbeat: Optional[datetime] = None  # Time when heartbeat monitoring started
        self.heartbeat: Optional[datetime] = None        # Last recorded heartbeat timestamp
        self.task: Optional[asyncio.Task] = None         # Asyncio task executing the job

    def set_task(self, task: asyncio.Task) -> None:
        """
        Associate an asyncio task with this job.

        Args:
            task (asyncio.Task): The asyncio Task to be assigned.
        """
        self.task = task

    def update_heartbeat(self, heartbeat: datetime) -> None:
        """
        Update the heartbeat timestamp for this job.
        If the start heartbeat is not set, initialize it with the current heartbeat.

        Args:
            heartbeat (datetime): The current heartbeat timestamp.
        """
        if self.start_heartbeat is None:
            self.start_heartbeat = heartbeat
        self.heartbeat = heartbeat
