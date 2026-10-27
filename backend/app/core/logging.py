import json
import logging


class SafeFormatter(logging.Formatter):
    def format(self, record):
        # Only explicit operational fields; never serialize request headers, bodies or exceptions.
        result = {"level": record.levelname, "event": record.getMessage()}
        for key in ("request_id", "method", "status", "duration_ms", "component"):
            if hasattr(record, key):
                result[key] = getattr(record, key)
        return json.dumps(result, ensure_ascii=False)


def configure_logging():
    logger = logging.getLogger("esc")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(SafeFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
