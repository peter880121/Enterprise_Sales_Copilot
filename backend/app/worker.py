import argparse
import logging
import signal
import tempfile
import threading
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db import Database
from app.discovery.processor import DiscoveryProcessor
from app.discovery.search_processor import SearchProcessor
from app.meetings.processor import MeetingProcessor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="Exit gracefully after one second")
    args = parser.parse_args()
    configure_logging()
    settings = get_settings()
    db = Database(settings)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    logger = logging.getLogger("esc")
    logger.info("worker_started_meeting_mock_handler")
    processor = MeetingProcessor(db, settings)
    discovery = DiscoveryProcessor(db, settings)
    search = SearchProcessor(db, settings)
    heartbeat = Path(tempfile.gettempdir()) / "esc-worker-heartbeat"

    def pulse():
        while not stop.is_set():
            heartbeat.touch()
            stop.wait(5)

    heartbeat_thread = threading.Thread(target=pulse, daemon=True)
    heartbeat_thread.start()
    timer = threading.Timer(1, stop.set) if args.smoke else None
    if timer:
        timer.start()
    try:
        while not stop.is_set():
            heartbeat.touch()
            worked = False
            if db.ready():
                for handler in (processor, discovery, search):
                    try:
                        worked = handler.process_one() or worked
                    except Exception:
                        logger.warning("job_handler_failed_no_payload_logged")
            stop.wait(0.2 if worked else 2)
    finally:
        stop.set()
        heartbeat_thread.join(timeout=2)
        if timer:
            timer.cancel()
        heartbeat.unlink(missing_ok=True)
        db.close()
        logger.info("worker_stopped")


if __name__ == "__main__":
    main()
