"""Zetaris, CheckAm's data layer. The official accounts list, regulator warnings and SEC notices are Zetaris tables
(see data/zetaris_setup.sql), loaded with SQL when the checker starts. Without Zetaris, the same data comes from
the local JSON files: that is sample mode, so CheckAm still runs with no Zetaris install or credentials.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path

import httpx

from .config import Settings
from .sources import official, regulators

log = logging.getLogger("checkam.zetaris")
SETUP = Path(__file__).resolve().parent / "data" / "zetaris_setup.sql"
NOTICES = Path(__file__).resolve().parent / "data" / "sec_notices.json"


loaded_from = "local files (sample mode)"  # set by load(); shown in the agent trace


class ZetarisError(RuntimeError):
    pass


class Zetaris:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def sql(self, statement: str, limit: int = 5000) -> list[list]:
        s = self.settings
        r = await self.client.post(
            f"{s.zetaris_rest_url}/sql-editor/sqls/run", timeout=120,
            json={"queryId": str(uuid.uuid4()), "sql": statement, "source": "SqlEditor", "limit": limit},
            headers={"Authorization": f"Bearer {s.zetaris_api_key}", "X-Org-ID": s.zetaris_org_id,
                     "X-Request-ID": str(uuid.uuid4())})
        if r.status_code >= 300:
            raise ZetarisError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        return (data.get("data") if isinstance(data, dict) else None) or []


def statements(sql: str) -> list[str]:
    """Split the setup file into single statements (Zetaris runs one at a time)."""
    body = "\n".join(line for line in sql.splitlines() if not line.strip().startswith("--"))
    return [part.strip() for part in body.split(";") if part.strip()]


def _split(cell) -> tuple[str, ...]:
    return tuple(p.strip().lower() for p in str(cell or "").split("|") if p.strip())


async def setup(settings: Settings, client: httpx.AsyncClient) -> list[str]:
    """Register CheckAm's sources in Zetaris. Safe to re-run: objects that already exist are kept."""
    z, out = Zetaris(settings, client), []
    for stmt in statements(SETUP.read_text(encoding="utf-8")):
        head = " ".join(stmt.split()[:5])
        try:
            await z.sql(stmt)
            out.append(f"OK    {head}")
        except ZetarisError as exc:
            if re.search(r"(?i)already exists", str(exc)):
                out.append(f"KEPT  {head} (already exists)")
            else:
                out.append(f"FAIL  {head}: {exc}")
    return out


async def load(settings: Settings, client: httpx.AsyncClient) -> str:
    """Point the official and regulator sources at Zetaris. Returns where the data came from, for the trace."""
    if not settings.zetaris_api_key:
        return "local files (sample mode: no ZETARIS_API_KEY)"
    z = Zetaris(settings, client)
    try:
        orgs = await z.sql("SELECT name, kind, aliases, domains, x_handles FROM checkam.official_accounts")
        warned = await z.sql("SELECT name, aliases, regulator, finding, url FROM checkam.regulator_warnings")
        rules = await z.sql("SELECT id, topic, regulator, finding, url FROM checkam.regulator_rules")
        notices = await z.sql("SELECT alias, name, title, url, regulator FROM checkam.sec_notices")
    except (ZetarisError, httpx.HTTPError) as exc:
        log.warning("Zetaris unavailable, using local files: %s", exc)
        return f"local files (Zetaris unavailable: {str(exc)[:80]})"
    if not orgs:
        return "local files (Zetaris returned no official accounts; run `python -m checkam zetaris`)"
    official.use([official.Org(str(n), str(k), _split(a), _split(d), _split(x)) for n, k, a, d, x in orgs])
    regulators.use(
        warned=[{"name": n, "aliases": list(_split(a)), "regulator": reg, "finding": f, "url": u} for n, a, reg, f, u in warned],
        rules=[{"id": i, "when": t, "regulator": reg, "finding": f, "url": u} for i, t, reg, f, u in rules],
        notices=[(str(a).lower(), n, t, u, reg) for a, n, t, u, reg in notices])
    return f"Zetaris ({len(orgs)} official accounts, {len(warned) + len(notices)} regulator warnings, {len(rules)} rules)"


def export_notices(rows: list[tuple[str, str, str, str, str]]) -> None:
    """Write the SEC notices `refresh` extracted, so the public sec_notices table in Zetaris can serve them."""
    notices = [{"alias": a, "name": n, "title": t, "url": u, "regulator": r} for a, n, t, u, r in rows]
    NOTICES.write_text(json.dumps({"_note": "SEC Nigeria illegal-operator notices extracted by `checkam refresh`.",
                                   "notices": notices}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
