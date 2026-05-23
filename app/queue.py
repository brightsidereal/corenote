import redis
from rq import Queue
from app.config import settings

conn = redis.from_url(settings.redis_url)
ingest_queue = Queue("ingest", connection=conn)