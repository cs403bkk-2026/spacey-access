"""mitmproxy addon: record every request/response that passes the tap.

The tap sits between spacey and spacey-access (reverse proxy), so every call
the hub makes to Access lands here as one JSON line. Local orchestration only:
the file holds access codes and the service token, so it stays in the capture
directory (outside every repo) and reports show it redacted.
"""

import json
import os
import time

OUT = os.environ.get("CAPTURE_FILE", "/captures/flows.jsonl")


def _write(record):
    with open(OUT, "a") as f:
        f.write(json.dumps(record) + "\n")


def response(flow):
    _write({
        "t": time.time(),
        "method": flow.request.method,
        "path": flow.request.path,
        "req_headers": dict(flow.request.headers),
        "req_body": flow.request.get_text(strict=False),
        "status": flow.response.status_code,
        "resp_headers": dict(flow.response.headers),
        "resp_body": flow.response.get_text(strict=False),
    })


def error(flow):
    _write({
        "t": time.time(),
        "method": flow.request.method,
        "path": flow.request.path,
        "req_headers": dict(flow.request.headers),
        "req_body": flow.request.get_text(strict=False),
        "status": 0,
        "error": str(flow.error),
    })
