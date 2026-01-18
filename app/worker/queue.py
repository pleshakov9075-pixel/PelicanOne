from redis import Redis
from rq import Queue

from app.config import settings

redis_conn = Redis.from_url(settings.redis_url)
queue = Queue("pelican", connection=redis_conn)


def enqueue_job(job_id: int) -> str:
    rq_job = queue.enqueue("app.worker.tasks.execute_task", job_id)
    return rq_job.id


def enqueue_broadcast(message: str) -> None:
    queue.enqueue("app.worker.tasks.broadcast_message", message)
