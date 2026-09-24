"""Published-service smoke check used by the Compose integration CI job.

This file is intentionally stdlib-only and executable directly:

    python backend/tests/integration/test_compose_services.py
"""

from __future__ import annotations

import json
import urllib.request


def _read(url: str) -> tuple[int, bytes]:
    with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - fixed localhost URLs
        return int(response.status), response.read()


def test_published_backend_and_frontend() -> None:
    backend_status, backend_body = _read("http://127.0.0.1:8000/health")
    assert backend_status == 200
    payload = json.loads(backend_body)
    assert payload["status"] == "healthy"
    assert payload["service"] == "Daisy Risk Engine"

    frontend_status, _ = _read("http://127.0.0.1:3000")
    assert frontend_status == 200


if __name__ == "__main__":
    test_published_backend_and_frontend()
    print("published backend and frontend smoke checks passed")
