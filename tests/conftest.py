from datetime import datetime, timedelta, timezone

import httpx
import pytest

from checkam.agent import Checker
from checkam.config import Settings
from checkam.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.db")


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "t.db", provider="offline")


def offline_transport(request: httpx.Request) -> httpx.Response:
    """No test touches the internet. RDAP says 'created 5 days ago' for *.xyz, 'not found' otherwise."""
    if request.url.host == "rdap.org":
        if request.url.path.endswith(".xyz"):
            made = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%dT00:00:00Z")
            return httpx.Response(200, json={"events": [{"eventAction": "registration", "eventDate": made}]})
        return httpx.Response(404)
    return httpx.Response(503)


@pytest.fixture
def checker(settings, store, monkeypatch):
    from checkam.sources import links
    monkeypatch.setattr(links, "_public_host", lambda host: False)  # never fetch pages in tests
    return Checker(settings, store, httpx.AsyncClient(transport=httpx.MockTransport(offline_transport)))
