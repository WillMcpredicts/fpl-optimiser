"""HTTP and Supabase helpers.

Writes go through PostgREST directly rather than supabase-py: upserts here are
always bulk and always merge-duplicates, and being explicit about that is worth
more than the convenience wrapper.
"""
from __future__ import annotations

import csv
import io
import sys
import time
from typing import Any, Iterable, Sequence

import requests

from config import SUPABASE_KEY, SUPABASE_URL

SESSION = requests.Session()
SESSION.headers["User-Agent"] = "fpl-optimiser/1.0 (personal use)"

CHUNK = 500


def log(msg: str) -> None:
    print(msg, flush=True)


def get_json(url: str, *, retries: int = 3) -> Any:
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=60)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001 - retry any transport failure
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log(f"  retry {attempt + 1}/{retries} for {url} after {exc} ({wait}s)")
            time.sleep(wait)
    return None


def get_csv(url: str, *, retries: int = 3, required: bool = True) -> list[dict[str, str]]:
    """Fetch a CSV into dicts. Returns [] for a missing optional file."""
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=120)
            if r.status_code == 404:
                if required:
                    raise FileNotFoundError(url)
                return []
            r.raise_for_status()
            return list(csv.DictReader(io.StringIO(r.text)))
        except FileNotFoundError:
            raise
        except Exception as exc:  # noqa: BLE001
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
            log(f"  retry {attempt + 1} for {url} after {exc}")
    return []


def _require_supabase() -> None:
    if not SUPABASE_URL or not SUPABASE_KEY:
        sys.exit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.\n"
            "Copy .env.example to .env.local and fill them in."
        )


def _headers(prefer: str) -> dict[str, str]:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }


def dedupe(rows: Sequence[dict], on_conflict: str) -> list[dict]:
    """Keep one row per conflict key, last occurrence winning.

    Postgres rejects an INSERT ... ON CONFLICT batch that touches the same key
    twice, and the source archives do contain repeats -- vaastav carries
    duplicate player-gameweek rows where a fixture was corrected after the fact.
    Deduping here rather than in each caller means no ingestion job can trip it.
    """
    keys = [k.strip() for k in on_conflict.split(",")]
    seen: dict[tuple, dict] = {}
    for r in rows:
        seen[tuple(r.get(k) for k in keys)] = r
    return list(seen.values())


def upsert(table: str, rows: Sequence[dict], *, on_conflict: str) -> int:
    """Bulk upsert, chunked. Returns the number of rows sent."""
    _require_supabase()
    if not rows:
        return 0

    deduped = dedupe(rows, on_conflict)
    if len(deduped) != len(rows):
        log(f"  {len(rows) - len(deduped)} duplicate {table} rows collapsed")
    rows = deduped
    url = f"{SUPABASE_URL}/rest/v1/{table}?on_conflict={on_conflict}"
    sent = 0
    for start in range(0, len(rows), CHUNK):
        batch = rows[start : start + CHUNK]
        r = SESSION.post(
            url,
            json=batch,
            headers=_headers("resolution=merge-duplicates,return=minimal"),
            timeout=120,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"upsert {table} failed [{r.status_code}]: {r.text[:800]}")
        sent += len(batch)
    return sent


def insert_rows(table: str, rows: Sequence[dict]) -> int:
    """Plain chunked insert, for tables whose rows are replaced wholesale.

    Deliberately not upsert: a table with a serial primary key has no usable
    conflict target, and upserting on it would make the dedupe in `upsert`
    collapse every row into one.
    """
    _require_supabase()
    if not rows:
        return 0
    sent = 0
    for start in range(0, len(rows), CHUNK):
        batch = rows[start : start + CHUNK]
        r = SESSION.post(
            f"{SUPABASE_URL}/rest/v1/{table}",
            json=batch,
            headers=_headers("return=minimal"),
            timeout=120,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"insert {table} failed [{r.status_code}]: {r.text[:800]}")
        sent += len(batch)
    return sent


def delete_where(table: str, filters: str) -> None:
    """Delete rows matching a PostgREST filter string, e.g. 'season=eq.2026-27'."""
    _require_supabase()
    r = SESSION.delete(
        f"{SUPABASE_URL}/rest/v1/{table}?{filters}",
        headers=_headers("return=minimal"),
        timeout=120,
    )
    if r.status_code >= 400:
        raise RuntimeError(f"delete {table} failed [{r.status_code}]: {r.text[:500]}")


def select(table: str, query: str) -> list[dict]:
    """Read rows back, paging past PostgREST's default 1000-row ceiling."""
    _require_supabase()
    out: list[dict] = []
    offset = 0
    page = 1000
    while True:
        r = SESSION.get(
            f"{SUPABASE_URL}/rest/v1/{table}?{query}&limit={page}&offset={offset}",
            headers=_headers("return=representation"),
            timeout=120,
        )
        if r.status_code >= 400:
            raise RuntimeError(f"select {table} failed [{r.status_code}]: {r.text[:500]}")
        rows = r.json()
        out.extend(rows)
        if len(rows) < page:
            return out
        offset += page


class Run:
    """Records an ingestion run so the UI can show real freshness, and a failed
    scrape shows as failed instead of quietly serving yesterday's numbers."""

    def __init__(self, source: str, season: str | None = None):
        self.source = source
        self.season = season
        self.rows = 0
        self.id: int | None = None

    def __enter__(self) -> "Run":
        _require_supabase()
        r = SESSION.post(
            f"{SUPABASE_URL}/rest/v1/ingest_runs",
            json={"source": self.source, "season": self.season, "status": "running"},
            headers=_headers("return=representation"),
            timeout=60,
        )
        if r.status_code < 400 and r.json():
            self.id = r.json()[0]["id"]
        log(f"[{self.source}] started")
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        status = "ok" if exc_type is None else "failed"
        detail = None if exc_type is None else f"{exc_type.__name__}: {exc}"[:1000]
        if self.id is not None:
            SESSION.patch(
                f"{SUPABASE_URL}/rest/v1/ingest_runs?id=eq.{self.id}",
                json={
                    "status": status,
                    "finished_at": "now()",
                    "rows_written": self.rows,
                    "detail": detail,
                },
                headers=_headers("return=minimal"),
                timeout=60,
            )
        log(f"[{self.source}] {status}: {self.rows} rows")
        return False


def to_int(v: Any, default: int | None = 0) -> int | None:
    try:
        if v is None or v == "":
            return default
        return int(float(v))
    except (TypeError, ValueError):
        return default


def to_float(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default
