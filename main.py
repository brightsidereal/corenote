import threading
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import init_db
from app.logger import setup_logging, log
from app.errors import CoreNoteError, corenote_error_handler, generic_error_handler
from app.middleware import RequestLoggingMiddleware
from app.routes import router
from app.oauth import router as oauth_router

def start_worker():
    """รัน RQ worker ใน background thread"""
    import redis
    from rq import Queue
    from rq.worker import SimpleWorker

    conn = redis.from_url(settings.redis_url)
    queue = Queue("ingest", connection=conn)
    worker = SimpleWorker([queue], connection=conn)
    log.info("worker_started")
    worker.work()

@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("startup", environment=settings.environment)
    init_db()
    log.info("database_ready")

    # รัน worker ใน background thread
    worker_thread = threading.Thread(target=start_worker, daemon=True)
    worker_thread.start()
    log.info("worker_thread_started")

    yield
    log.info("shutdown")

app = FastAPI(
    title="CoreNote API",
    version="1.0.0",
    description="Cognitive note-taking system",
    lifespan=lifespan,
    docs_url="/docs" if settings.environment == "development" else None,
    redoc_url=None,
)

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.environment == "development" else [settings.base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(CoreNoteError, corenote_error_handler)
app.add_exception_handler(Exception, generic_error_handler)

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}

app.include_router(router)
app.include_router(oauth_router)