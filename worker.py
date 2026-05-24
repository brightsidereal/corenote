import os
from dotenv import load_dotenv
load_dotenv()

import redis
from rq import Queue
from rq.worker import SimpleWorker

from app.config import settings

conn = redis.from_url(settings.redis_url)
queue = Queue('ingest', connection=conn)

if __name__ == '__main__':
    worker = SimpleWorker([queue], connection=conn)
    print('worker started -- listening on queue: ingest')
    worker.work()
