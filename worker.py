import os
from dotenv import load_dotenv
load_dotenv()

import redis
from rq import Queue
from rq.worker import SimpleWorker  # ใช้ SimpleWorker สำหรับ Windows

from app.config import REDIS_URL

conn = redis.from_url(REDIS_URL)
queue = Queue("ingest", connection=conn)

if __name__ == "__main__":
    worker = SimpleWorker([queue], connection=conn)
    print("worker started — listening on queue: ingest")
    worker.work()