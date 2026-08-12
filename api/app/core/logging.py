"""specs/02-architecture.md § Observability: "Content-free structured logs (org_id,
doc_id, job ids, timings — never text spans or filenames beyond hashed form in shared
infra logs)." One JSON line per record, to stdout — ECS's awslogs driver (already
configured on every task; see infra/modules/ecs) ships stdout straight to CloudWatch
Logs, which is exactly what a CloudWatch Logs metric filter needs to match against (see
infra/modules/alerting's module docstring for the two alarms this exists to unblock).

Call sites: `logging.getLogger(__name__).warning("event_name", extra={"event": ...,
"org_id": ..., "doc_id": ...})`. `extra` fields land as top-level JSON keys.

NEVER pass document text, filenames, justifications, or any other customer content as a
log field or in the log message itself — that's CLAUDE.md invariant #6, and the whole
reason app/core/errors.py's handler goes through app/crypto's-adjacent care (see its own
`_safe_exception_summary` docstring) rather than just logging str(exc) everywhere.
"""

import json
import logging
import sys
from datetime import UTC, datetime

_RESERVED_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_ATTRS and key not in payload:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
