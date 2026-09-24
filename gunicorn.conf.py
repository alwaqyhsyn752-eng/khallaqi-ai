"""Gunicorn configuration for FastAPI."""
import multiprocessing
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
backlog = 2048

workers = int(os.getenv("WORKERS", "2"))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
timeout = 120
graceful_timeout = 30
keepalive = 5

accesslog = "-"
errorlog = "-"
loglevel = os.getenv("LOG_LEVEL", "info").lower()
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(L)s'

proc_name = "khallaqi"
preload_app = True
forwarded_allow_ips = "*"
