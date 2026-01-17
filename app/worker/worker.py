import os
from redis import Redis
from rq import Worker

from app.config import settings


def main() -> None:
    redis_conn = Redis.from_url(settings.redis_url)
    queues = ["pelican"]
    worker = Worker(queues, connection=redis_conn)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    main()
