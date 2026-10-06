import logging
import os


MAX_LOG_BYTES = 10 * 1024 * 1024
REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILE = os.path.join(REPO_DIR, "logs", "console.log")


class SingleFileSizeHandler(logging.FileHandler):
    """Append to one UTF-8 log file and replace it when the next record would exceed the size limit."""

    def __init__(self, filename, max_bytes):
        self.max_bytes = max_bytes
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        super().__init__(filename, mode="a", encoding="utf-8", delay=False)

    def emit(self, record):
        try:
            message = self.format(record) + self.terminator
            incoming_bytes = len(message.encode("utf-8", errors="replace"))
            current_bytes = os.path.getsize(self.baseFilename) if os.path.exists(self.baseFilename) else 0

            if current_bytes + incoming_bytes > self.max_bytes:
                if self.stream is not None:
                    self.stream.close()
                self.stream = open(
                    self.baseFilename,
                    "w",
                    encoding=self.encoding or "utf-8",
                    errors=self.errors,
                )

            super().emit(record)
        except Exception:
            self.handleError(record)


def configure_runtime_logging():
    """Add file logging without replacing Uvicorn's existing console handlers."""
    handler = SingleFileSizeHandler(LOG_FILE, MAX_LOG_BYTES)
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s: %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    # Uvicorn owns its console configuration. Add one file handler to each
    # non-propagating branch so startup/error/access messages are captured too.
    logging.getLogger().addHandler(handler)
    logging.getLogger("uvicorn").addHandler(handler)
    logging.getLogger("uvicorn.access").addHandler(handler)
