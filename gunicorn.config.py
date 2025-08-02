import os

# Configuración para Gunicorn
bind = f"0.0.0.0:{os.environ.get('PORT', 8080)}"
workers = 1
worker_class = "aiohttp.GunicornWebWorker"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 100
timeout = 30
keepalive = 5
preload_app = True

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"
access_log_format = '%h %l %u %t "%r" %s %b "%{Referer}i" "%{User-Agent}i"'