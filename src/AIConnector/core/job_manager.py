import asyncio
import uuid
import logging
from typing import Any, Callable, Awaitable, Dict, List, Optional

from AIConnector.common.message import MessageTypes
from .job import Job

logger = logging.getLogger(__name__)


class JobManager:
    """
    Manages asynchronous jobs by creating, monitoring, and reporting their status.
    """

    def __init__(self, send_message_callback: Callable[..., Awaitable[None]]) -> None:
        """
        Initialize the JobManager.

        Args:
            send_message_callback (Callable[..., Awaitable[None]]):
                Asynchronous callback to send messages about job status.
        """
        self.send_message_callback: Callable[..., Awaitable[None]] = send_message_callback
        self.active_jobs: Dict[str, Job] = {}  # Maps job IDs to Job instances
        self.jobs: List[Callable[[Any], Awaitable[Any]]] = []  # Registered job callables
        self.monitoring_task: Optional[asyncio.Task[Any]] = None  # Task for monitoring jobs
        self.job_futures: Dict[str, asyncio.Future[Any]] = {}  # Futures for job results

    async def create_job(
        self,
        data: Any,
        job_callable: Callable[[Any], Awaitable[Any]],
        peer_id: str,
        queue_id: str,
    ) -> str:
        """
        Create a new job, start its asynchronous task, and notify via system messages.

        Args:
            data (Any): Data associated with the job.
            job_callable (Callable[[Any], Awaitable[Any]]): Asynchronous callable to process the job.
            peer_id (str): Identifier of the peer associated with the job.
            queue_id (str): Identifier for the job queue.

        Returns:
            str: A unique job identifier.
        """
        # Generate a unique job ID.
        job_id = str(uuid.uuid4())
        # Create a new job instance and store it.
        job = Job(job_id, data, peer_id, queue_id)
        self.active_jobs[job_id] = job

        # Create a future to await the job's result.
        future = asyncio.get_event_loop().create_future()
        self.job_futures[job_id] = future

        # Notify that the job has been initialized.
        await self.send_message_callback(
            message_type=MessageTypes.SYSTEM_MESSAGE.value,
            job_id=job_id,
            peer_id=peer_id,
            queue_id=queue_id,
            text=f"Job initialized with id {job_id}",
        )

        # Start the job's asynchronous task.
        job.task = asyncio.create_task(job_callable(data))
        # Notify that the job has started.
        await self.send_message_callback(
            message_type=MessageTypes.SYSTEM_MESSAGE.value,
            job_id=job_id,
            peer_id=peer_id,
            queue_id=queue_id,
            text=f"Job started with id {job_id}",
        )
        return job_id

    async def start_monitoring(self, interval: float = 1) -> None:
        """
        Continuously monitor active jobs, sending heartbeat and final messages.

        Args:
            interval (float): Time (in seconds) between monitoring checks.
        """
        while True:
            finished_jobs: List[str] = []
            # Iterate through a copy of active jobs to safely modify the dictionary.
            for job_id, job in list(self.active_jobs.items()):
                peer_id = job.peer_id
                queue_id = job.queue_id
                if job.task.done():
                    try:
                        # Get the result of the job.
                        result = job.task.result()
                    except Exception as e:
                        logger.error(f"[JobManager] Error: {e}")
                        result = f"Job error: {e}"

                    # Set the result for the awaiting future.
                    future = self.job_futures.get(job_id)
                    if future and not future.done():
                        future.set_result(result)

                    # Notify that the job has finished.
                    await self.send_message_callback(
                        message_type=MessageTypes.FINAL_MESSAGE.value,
                        job_id=job_id,
                        peer_id=peer_id,
                        queue_id=queue_id,
                        text=result,
                    )
                    finished_jobs.append(job_id)
                else:
                    # Send a heartbeat message to indicate the job is still running.
                    await self.send_message_callback(
                        message_type=MessageTypes.HEARTBEAT.value,
                        job_id=job_id,
                        queue_id=queue_id,
                        peer_id=peer_id,
                        text="working",
                    )

            # Clean up finished jobs.
            for job_id in finished_jobs:
                del self.active_jobs[job_id]
                if job_id in self.job_futures:
                    del self.job_futures[job_id]

            await asyncio.sleep(interval)

    async def await_job_result(self, job_id: str, timeout: Optional[float] = None) -> Any:
        """
        Await the result of a specific job.

        Args:
            job_id (str): The unique job identifier.
            timeout (Optional[float]): Optional timeout (in seconds).

        Returns:
            Any: The result of the job.

        Raises:
            ValueError: If the job does not exist.
        """
        future = self.job_futures.get(job_id)
        if not future:
            raise ValueError(f"Job with {job_id=} doesn't exist")
        return await asyncio.wait_for(future, timeout=timeout)

    def start(self, interval: float = 1) -> None:
        """
        Start monitoring active jobs.

        Args:
            interval (float): Time (in seconds) between monitoring checks.
        """
        self.monitoring_task = asyncio.create_task(self.start_monitoring(interval))

    async def stop(self) -> None:
        """
        Stop monitoring active jobs by cancelling the monitoring task.
        """
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

    async def process_message(self, msg: str, from_id: str, queue_id: str) -> None:
        """
        Process an incoming message by creating a job using the first registered job callable.

        Args:
            msg (str): The message data.
            from_id (str): Identifier of the peer that sent the message.
            queue_id (str): Identifier for the job queue.
        """
        if self.jobs:
            job_callable = self.jobs[0]
            job_id = await self.create_job(msg, job_callable, from_id, queue_id)
            await self.send_message_callback(
                message_type=MessageTypes.SYSTEM_MESSAGE.value,
                job_id=job_id,
                peer_id=from_id,
                queue_id=queue_id,
                text=f"Ack: created job with id {job_id} for peer {from_id}",
            )

    def register_job(self, job_call_back: Callable[[Any], Awaitable[Any]]) -> None:
        """
        Register a new job callable.

        Args:
            job_call_back (Callable[[Any], Awaitable[Any]]):
                Asynchronous callable that processes job data.
        """
        self.jobs.append(job_call_back)

    def job_list(self) -> List[Callable[[Any], Awaitable[Any]]]:
        """
        Get the list of registered job callables.

        Returns:
            List[Callable[[Any], Awaitable[Any]]]: A list of job callables.
        """
        return list(self.jobs)

    def job_active_list(self) -> Dict[str, Job]:
        """
        Get the dictionary of currently active jobs.

        Returns:
            Dict[str, Job]: A mapping of job IDs to Job instances.
        """
        return self.active_jobs
