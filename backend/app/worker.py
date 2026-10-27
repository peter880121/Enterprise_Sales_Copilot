import argparse
import logging
import signal
import tempfile
import threading
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import Database


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Exit gracefully after one second")
    args = parser.parse_args()
    configure_logging()
    db = Database(get_settings())
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    logger = logging.getLogger("esc")
    logger.info("worker_skeleton_started_no_business_handlers")
    heartbeat = Path(tempfile.gettempdir()) / "esc-worker-heartbeat"
    timer = threading.Timer(1, stop.set) if args.smoke else None
    if timer:
        timer.start()
    try:
        while not stop.is_set():
            heartbeat.touch()
            stop.wait(5)
    finally:
        if timer:
            timer.cancel()
        heartbeat.unlink(missing_ok=True)
        db.close()
        logger.info("worker_stopped")


if __name__ == "__main__":
    main()
