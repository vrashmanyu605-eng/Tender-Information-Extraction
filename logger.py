import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler

# Ensure log folder exists
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

# Daily log file: logs/YYYY-MM-DD.log
today_str = datetime.now().strftime("%Y-%m-%d")
log_file_path = os.path.join(LOG_DIR, f"{today_str}.log")

# FORMAT
formatter = logging.Formatter("[%(levelname)s] %(asctime)s - %(name)s - %(message)s")

# Console output
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

# File output: rotate daily
file_handler = TimedRotatingFileHandler(
    filename=log_file_path,
    when="midnight",
    interval=1,
    backupCount=30,              # Keep last 30 days
    encoding="utf-8",
    delay=False
)
file_handler.setFormatter(formatter)
file_handler.suffix = "%Y-%m-%d"  # Optional: sets suffix like 2025-07-24

# Create app logger
app_logger = logging.getLogger("app")
app_logger.setLevel(logging.INFO)

# SQLAlchemy pool connection logger
sql_logger = logging.getLogger("sqlalchemy.pool")
sql_logger.setLevel(logging.INFO)

# Optional: show SQL statements
sql_stmt_logger = logging.getLogger("sqlalchemy.engine")
sql_stmt_logger.setLevel(logging.WARNING)

# Attach handlers if not already present
for logger in (app_logger, sql_logger, sql_stmt_logger):
    if not logger.hasHandlers():
        logger.addHandler(console_handler)
        logger.addHandler(file_handler)
