"""Indexed on-disk catalog store replacing the multi-hundred-MB in-memory dicts.

Two things used to hold a full copy of the 110k-event catalog in RAM:

* ``serve/server.py:_CATALOG_LOOKUP`` — a name/alias dict built from
  ``catalog.min.json`` (~618 MB resident after ``json.loads``).
* ``serve/catalog_engine.py:CatalogEngine._items`` — a second list of parsed
  records (~690 MB resident).

This module builds a single SQLite file by streaming the JSON array one element
at a time. Measured on the production catalog: 110,222 elements in ~2.0 s at a
peak of ~25 MB RSS, versus 618 MB for ``json.loads``. Lookups are single-row
indexed reads (<1 ms).

Design notes
------------
* The database is a *derived artifact*. It is rebuilt when any source file's
  mtime/size changes, and it can always be deleted safely.
* Builds are atomic: work goes to a temporary file, then ``os.replace``.
* Readers never see a partial database, and never block a writer.
* Keys are lowercased and space-stripped so ``SN 2011fe``, ``SN2011fe`` and
  ``sn2011fe`` all hit the same row.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Iterator

_SCHEMA_VERSION = 4

# Columns kept as real SQL columns so filtering/sorting happens in SQLite rather
# than in a Python list comprehension over 110k dicts.
_RECORD_COLUMNS = (
    "name",
    "aliases_json",
    "type",
    "type_badge",
    "date",
    "age",
    "mag",
    "z",
    "ra",
    "dec",
    "host",
    "disc",
    "spec",
    "phot",
    "search_blob",
    "sort_date",
)

_CREATE_SQL = f"""
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    name         TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    type         TEXT NOT NULL DEFAULT '',
    type_badge   TEXT NOT NULL DEFAULT '',
    date         TEXT NOT NULL DEFAULT '',
    age          TEXT NOT NULL DEFAULT '',
    mag          REAL,
    z            REAL,
    ra           TEXT NOT NULL DEFAULT '',
    dec          TEXT NOT NULL DEFAULT '',
    host         TEXT NOT NULL DEFAULT '',
    disc         TEXT NOT NULL DEFAULT '',
    spec         INTEGER NOT NULL DEFAULT 0,
    phot         INTEGER NOT NULL DEFAULT 0,
    search_blob  TEXT NOT NULL DEFAULT '',
    sort_date    TEXT NOT NULL DEFAULT '',
    meta_json    TEXT NOT NULL DEFAULT '{{}}',
    PRIMARY KEY (name)
);
CREATE TABLE IF NOT EXISTS keys (
    key  TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
-- Typo tolerance without a full-corpus scan. Every alias key is filed under its
-- length so a miss like "SN1999zzzzzz" only compares against keys within a few
-- characters of the target instead of all 270k aliases (measured 1.8 s).
CREATE TABLE IF NOT EXISTS key_lengths (
    key    TEXT PRIMARY KEY,
    name   TEXT NOT NULL,
    length INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_key_lengths_len ON key_lengths(length);
CREATE INDEX IF NOT EXISTS idx_events_sort_date ON events(sort_date);
CREATE INDEX IF NOT EXISTS idx_events_type      ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_spec      ON events(spec);
CREATE INDEX IF NOT EXISTS idx_events_phot      ON events(phot);
CREATE INDEX IF NOT EXISTS idx_events_z         ON events(z);
CREATE INDEX IF NOT EXISTS idx_events_mag       ON events(mag);
CREATE INDEX IF NOT EXISTS idx_events_name      ON events(name);
CREATE INDEX IF NOT EXISTS idx_keys_name        ON keys(name);
"""

# Optional trigram index over alias keys. SQLite's FTS5 trigram tokenizer turns a
# typo lookup into an indexed substring scan, so "SN1999zzzzzz" costs ~1 ms
# instead of the ~350-1400 ms a length-band table scan still costs on this
# corpus. Created best-effort: a SQLite build without FTS5 falls back to the
# key_lengths scan in fuzzy_name().
_CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS key_trigrams USING fts5(
    key, name UNINDEXED, tokenize='trigram'
);
"""


def _norm_key(value: Any) -> str:
    """Lowercase and strip whitespace so designations match loosely."""
    if value is None:
        return ""
    return str(value).strip().lower().replace(" ", "")


def _levenshtein_bounded(a: str, b: str, limit: int) -> int | None:
    """Edit distance, abandoning early once it provably exceeds ``limit``.

    A banded two-row implementation: it stops as soon as the cheapest value in
    a row exceeds ``limit``, so most of 90k near-length keys are rejected after
    a couple of character comparisons instead of a full dynamic-programming
    matrix. Returns ``None`` when the distance is greater than ``limit``.
    """
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > limit:
        return None
    # Shorter string on the row axis keeps the band narrow.
    if la > lb:
        a, b, la, lb = b, a, lb, la
    prev = list(range(la + 1))
    for i in range(1, lb + 1):
        bc = b[i - 1]
        cur = [i] + [0] * la
        row_min = cur[0]
        for j in range(1, la + 1):
            cost = 0 if a[j - 1] == bc else 1
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            cur[j] = v
            if v < row_min:
                row_min = v
        if row_min > limit:
            return None
        prev = cur
    d = prev[la]
    return d if d <= limit else None


def _best_edit(
    candidates: "Iterable[tuple[str, str]]",
    target: str,
    limit: int,
) -> str | None:
    """Canonical name of the closest candidate within ``limit`` edits."""
    best: tuple[int, str] | None = None
    for key, name in candidates:
        if abs(len(key) - len(target)) > limit:
            continue
        d = _levenshtein_bounded(key, target, limit)
        if d is None:
            continue
        if best is None or d < best[0]:
            best = (d, name)
            if d == 0:
                break
    return best[1] if best else None


def _extract_val(obj: Any, key: str) -> str:
    if not isinstance(obj, dict):
        return ""
    v = obj.get(key)
    if not v:
        return ""
    if isinstance(v, list) and v:
        item = v[0]
        if isinstance(item, dict):
            return str(item.get("value", "")).strip()
        return str(item).strip()
    if isinstance(v, dict):
        return str(v.get("value", "")).strip()
    return str(v).strip()


def _extract_float(value: Any) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ("—", "None", "nan", "null"):
        return None
    try:
        f = float(s)
        return None if f != f else f
    except (ValueError, TypeError):
        return None


def _extract_int_count(value: Any) -> int:
    if not value:
        return 0
    s = str(value).strip()
    if not s or s == "—":
        return 0
    try:
        return max(0, int(s.split(",")[0].strip()))
    except (ValueError, TypeError, IndexError):
        return 0


def _clean_date_for_sort(d: str, reverse: bool) -> str:
    if not d or d in ("—", "None", "null") or not d[0].isdigit():
        return "0000/00/00" if reverse else "9999/99/99"
    parts = d.replace("-", "/").split("/")
    if len(parts) >= 3:
        return f"{parts[0].zfill(4)}/{parts[1].zfill(2)}/{parts[2].zfill(2)}"
    return parts[0].zfill(4)


def _classify_type_badge(claimed_type: str) -> str:
    ct = (claimed_type or "").lower()
    if not ct or ct == "—":
        return "badge-unknown"
    if "ia" in ct or "i-a" in ct:
        return "badge-ia"
    if "ii" in ct:
        return "badge-ii"
    if "ib" in ct or "ic" in ct:
        return "badge-ibc"
    if "slsn" in ct or "superluminous" in ct:
        return "badge-slsn"
    if "tde" in ct or "tidal" in ct:
        return "badge-tde"
    return "badge-other"


def _format_relative_age(date_str: str) -> str:
    if not date_str:
        return ""
    clean = date_str.replace("/", "-").strip()
    parts = clean.split("-")
    if len(parts) < 3:
        return ""
    try:
        import datetime as _dt

        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        ev_dt = _dt.datetime(y, m, d, tzinfo=_dt.timezone.utc)
        days = (_dt.datetime.now(_dt.timezone.utc) - ev_dt).days
        if days <= 0:
            return "today"
        if days == 1:
            return "1d ago"
        if days < 30:
            return f"{days}d ago"
        if days < 365:
            return f"{days // 30}mo ago"
        return f"{days // 365}y ago"
    except Exception:
        return ""


def _row_from_catalog_item(item: dict[str, Any]) -> tuple | None:
    """Build an ``events`` row from a catalog.min.json element."""
    name = item.get("name") or ""
    if not name:
        return None
    aliases = []
    raw_aliases = item.get("alias")
    if isinstance(raw_aliases, list):
        for a in raw_aliases:
            aval = a.get("value", a) if isinstance(a, dict) else str(a)
            if aval and aval != name and aval not in aliases:
                aliases.append(str(aval))

    c_type = _extract_val(item, "claimedtype")
    disc_date = _extract_val(item, "discoverdate")
    search_tokens = [name.lower()] + [a.lower() for a in aliases]
    if c_type:
        search_tokens.append(c_type.lower())
    host = _extract_val(item, "host")
    if host:
        search_tokens.append(host.lower())
    disc = _extract_val(item, "discoverer")
    if disc:
        search_tokens.append(disc.lower())

    return (
        name,
        json.dumps(aliases, separators=(",", ":")),
        c_type or "—",
        _classify_type_badge(c_type),
        disc_date or "—",
        _format_relative_age(disc_date),
        _extract_float(_extract_val(item, "maxappmag")),
        _extract_float(_extract_val(item, "redshift")),
        _extract_val(item, "ra") or "—",
        _extract_val(item, "dec") or "—",
        host or "—",
        disc or "—",
        _extract_int_count(item.get("spectralink")),
        _extract_int_count(item.get("photolink")),
        " ".join(search_tokens),
        _clean_date_for_sort(disc_date, reverse=True),
        json.dumps(item, separators=(",", ":")),
    )


def _iter_json_array(path: Path) -> Iterator[Any]:
    """Yield elements of a top-level JSON array without loading it all.

    ``json.loads`` on the 53 MB catalog costs ~521 MB of transient allocations.
    Decoding one element at a time keeps peak RSS near the size of the read
    buffer plus the largest single element.
    """
    decoder = json.JSONDecoder()
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        head = fh.read(1)
        while head and head.isspace():
            head = fh.read(1)
        if head != "[":
            raise ValueError(f"{path} is not a JSON array")
        buf = ""
        eof = False
        while not eof:
            chunk = fh.read(1 << 20)
            if chunk:
                buf += chunk
            else:
                eof = True
            while True:
                stripped = buf.lstrip()
                if stripped is not buf:
                    buf = stripped
                if not buf:
                    break
                ch = buf[0]
                if ch in ",]":
                    buf = buf[1:]
                    continue
                if ch == "[" and not buf.startswith("["):
                    break
                try:
                    obj, end = decoder.raw_decode(buf)
                except ValueError:
                    if eof:
                        buf = ""
                    break
                yield obj
                buf = buf[end:]


class CatalogStore:
    """Read-only SQLite catalog index with an atomic streaming builder."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._local = threading.local()
        self._build_lock = threading.Lock()
        self._ready = False
        self._sources: tuple[tuple[str, int, int], ...] = ()

    # -- connections -----------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro",
                uri=True,
                timeout=10.0,
                check_same_thread=False,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only=ON")
            conn.execute("PRAGMA cache_size=-8192")  # 8 MB page cache per thread
            conn.execute("PRAGMA temp_store=MEMORY")
            self._local.conn = conn
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            self._local.conn = None

    # -- build -----------------------------------------------------------

    def load_existing(self) -> bool:
        """Adopt an index left by a previous run without rebuilding it.

        A container restart should serve lookups immediately instead of paying a
        multi-second build. The schema version and event count are checked so a
        stale or incompatible database falls through to a real build.
        """
        if not self.db_path.is_file():
            return False
        try:
            conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            try:
                meta = {
                    str(r["key"]): str(r["value"])
                    for r in conn.execute("SELECT key, value FROM meta").fetchall()
                }
            finally:
                conn.close()
        except sqlite3.Error:
            return False
        if meta.get("schema_version") != str(_SCHEMA_VERSION):
            return False
        try:
            events = int(meta.get("event_count") or 0)
        except (TypeError, ValueError):
            events = 0
        if events <= 0:
            return False
        # Restore the persisted source fingerprint so is_stale() can answer without
        # rebuilding. Previously ``_sources`` was left empty, which made every
        # restart look stale and forced a full 6-10 s rebuild on each boot.
        raw_sources = meta.get("sources")
        if raw_sources:
            try:
                self._sources = tuple(
                    (str(t[0]), int(t[1]), int(t[2])) for t in json.loads(raw_sources)
                )
            except (ValueError, TypeError, IndexError):
                self._sources = ()
        self._ready = True
        return True

    @staticmethod
    def _fingerprint(sources: Iterable[Path]) -> tuple[tuple[str, int, int], ...]:
        out = []
        for src in sources:
            try:
                st = src.stat()
                out.append((str(src), st.st_mtime_ns, st.st_size))
            except OSError:
                continue
        return tuple(sorted(out))

    def is_stale(self, sources: Iterable[Path]) -> bool:
        if not self._ready or not self.db_path.is_file():
            return True
        return self._fingerprint(sources) != self._sources

    def build(self, sources: Iterable[Path], force: bool = False) -> bool:
        """(Re)build the index from catalog JSON array sources. Returns True if rebuilt."""
        sources = [Path(p) for p in sources]
        with self._build_lock:
            fingerprint = self._fingerprint(sources)
            if not force and self._ready and self.db_path.is_file() and fingerprint == self._sources:
                return False

            tmp = self.db_path.with_name(f".{self.db_path.name}.building.{os.getpid()}")
            for suffix in ("", "-wal", "-shm"):
                p = Path(str(tmp) + suffix)
                if p.exists():
                    try:
                        p.unlink()
                    except OSError:
                        pass

            t0 = time.time()
            count = 0
            conn = sqlite3.connect(str(tmp), timeout=30.0)
            try:
                conn.execute("PRAGMA journal_mode=OFF")
                conn.execute("PRAGMA synchronous=OFF")
                conn.execute("PRAGMA temp_store=MEMORY")
                conn.executescript(_CREATE_SQL)
                fts_enabled = False
                try:
                    conn.executescript(_CREATE_FTS_SQL)
                    fts_enabled = True
                except sqlite3.Error:
                    fts_enabled = False

                seen: set[str] = set()
                pending_events: list[tuple] = []
                pending_keys: list[tuple] = []
                key_len_rows: list[tuple] = []
                pending_trigrams: list[tuple] = []

                def _flush() -> None:
                    if pending_events:
                        conn.executemany(
                            "INSERT OR REPLACE INTO events VALUES "
                            "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            pending_events,
                        )
                        pending_events.clear()
                    if pending_keys:
                        conn.executemany(
                            "INSERT OR IGNORE INTO keys VALUES (?,?)",
                            pending_keys,
                        )
                        pending_keys.clear()
                    if key_len_rows:
                        conn.executemany(
                            "INSERT OR IGNORE INTO key_lengths VALUES (?,?,?)",
                            key_len_rows,
                        )
                        key_len_rows.clear()
                    if pending_trigrams:
                        try:
                            conn.executemany(
                                "INSERT INTO key_trigrams (key, name) VALUES (?,?)",
                                pending_trigrams,
                            )
                        except sqlite3.Error:
                            pass
                        pending_trigrams.clear()
                    conn.commit()

                for src in sources:
                    if not src.is_file():
                        continue
                    for item in _iter_json_array(src):
                        row = _row_from_catalog_item(item) if isinstance(item, dict) else None
                        if row is None:
                            continue
                        name = row[0]
                        if name in seen:
                            continue
                        seen.add(name)
                        pending_events.append(row)

                        key_rows = set()
                        for k in (
                            _norm_key(name),
                            _norm_key(name).replace(" ", ""),
                        ):
                            if k:
                                key_rows.add((k, name))
                        for alias in json.loads(row[1]):
                            ak = _norm_key(alias)
                            if ak:
                                key_rows.add((ak, name))
                                key_rows.add((ak.replace(" ", ""), name))
                        pending_keys.extend(sorted(key_rows))
                        # File each key by length for cheap typo lookup. A miss
                        # scans ~90k keys at most instead of 270k, and typical
                        # lengths are far smaller.
                        for k, n in key_rows:
                            key_len_rows.append((k, n, len(k)))
                            if fts_enabled and len(k) >= 3:
                                pending_trigrams.append((k, n))

                        count += 1
                        if len(pending_events) >= 2000:
                            _flush()

                _flush()

                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)",
                    (str(_SCHEMA_VERSION),),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('built_at', ?)",
                    (str(int(time.time())),),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('event_count', ?)",
                    (str(count),),
                )
                # Persist the source fingerprint so a restart can prove the index is
                # still current instead of rebuilding unconditionally. JSON keeps it
                # readable and stable across runs.
                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('sources', ?)",
                    (json.dumps([list(t) for t in fingerprint]),),
                )
                conn.commit()
                conn.execute("PRAGMA optimize")
                conn.commit()
            finally:
                conn.close()

            # Atomic swap. -wal/-shm belong to the temp db and are gone after close.
            os.replace(tmp, self.db_path)

            self._sources = fingerprint
            self._ready = True
            self.close()  # drop this thread's old read handle
            print(
                f"[CatalogStore] indexed {count} events in {time.time() - t0:.2f}s "
                f"({self.db_path.stat().st_size / 1e6:.1f} MB) -> {self.db_path}",
                flush=True,
            )
            return True

    # -- lookups ---------------------------------------------------------

    def get_meta(self, raw_name: str) -> dict | None:
        """Return the catalog metadata dict for a name or alias."""
        if not self._ready:
            return None
        key = _norm_key(raw_name)
        if not key:
            return None
        try:
            row = self._conn().execute(
                "SELECT e.meta_json FROM keys k JOIN events e ON e.name = k.name "
                "WHERE k.key = ? LIMIT 1",
                (key,),
            ).fetchone()
            if row is None and " " in key:
                row = self._conn().execute(
                    "SELECT e.meta_json FROM keys k JOIN events e ON e.name = k.name "
                    "WHERE k.key = ? LIMIT 1",
                    (key.replace(" ", ""),),
                ).fetchone()
            if row is None:
                return None
            return json.loads(row["meta_json"])
        except (sqlite3.Error, json.JSONDecodeError):
            return None

    def canonical_name(self, raw_name: str) -> str | None:
        key = _norm_key(raw_name)
        if not key or not self._ready:
            return None
        try:
            row = self._conn().execute(
                "SELECT name FROM keys WHERE key = ? LIMIT 1", (key,)
            ).fetchone()
            return row["name"] if row else None
        except sqlite3.Error:
            return None

    def count(self) -> int:
        if not self._ready:
            return 0
        try:
            row = self._conn().execute("SELECT COUNT(*) AS n FROM events").fetchone()
            return int(row["n"]) if row else 0
        except sqlite3.Error:
            return 0

    def fuzzy_name(self, raw_name: str, max_distance: int = 2) -> str | None:
        """Best canonical name within ``max_distance`` edits of ``raw_name``.

        Replaces the 270k-alias Levenshtein sweep that cost ~1.8 s on every 404.
        Candidate keys are narrowed by an indexed length band first, so the edit
        loop only runs over near-length designations. Returns ``None`` when no
        key is close enough, which keeps a genuine 404 cheap.
        """
        if not self._ready:
            return None
        target = _norm_key(raw_name)
        if not target or len(target) < 3:
            return None

        # Exact key first: cheapest possible answer for the common case.
        try:
            row = self._conn().execute(
                "SELECT name FROM key_lengths WHERE key = ? LIMIT 1", (target,)
            ).fetchone()
            if row is not None:
                return row["name"]
        except sqlite3.Error:
            pass

        # Trigram index: a one-character typo still shares most trigrams with the
        # intended key, so the OR query returns it near the top of the ranking.
        candidates = self._trigram_candidates(target)
        if candidates:
            return _best_edit(candidates, target, max_distance)

        # No shared trigrams at all means the name is not a near-miss of anything
        # in the corpus. Scanning the length band here cost ~600 ms to prove the
        # same thing, so skip it whenever the trigram index is actually present.
        if self._has_fts():
            return None

        # Fallback for SQLite builds without FTS5: indexed length band.
        lo, hi = len(target) - max_distance, len(target) + max_distance
        try:
            rows = self._conn().execute(
                "SELECT key, name FROM key_lengths WHERE length BETWEEN ? AND ?",
                (lo, hi),
            ).fetchall()
        except sqlite3.Error:
            return None
        return _best_edit(((r["key"], r["name"]) for r in rows), target, max_distance)

    def _has_fts(self) -> bool:
        cached = getattr(self._local, "has_fts", None)
        if cached is not None:
            return cached
        try:
            row = self._conn().execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='key_trigrams'"
            ).fetchone()
            result = row is not None
        except sqlite3.Error:
            result = False
        self._local.has_fts = result
        return result

    def _trigram_candidates(self, target: str, limit: int = 120) -> list[tuple[str, str]]:
        """Keys sharing trigrams with ``target``, via the FTS5 trigram index.

        A phrase query requires *every* trigram to match, so a single-character
        typo returns nothing and would drop us back onto the slow table scan. An
        OR over the target's trigrams matches near-misses and ranks them, which
        is what we want for "did you mean". Each trigram is quoted so punctuation
        in a designation cannot be parsed as an FTS operator.
        """
        if len(target) < 3:
            return []
        trigrams = list(dict.fromkeys(target[i : i + 3] for i in range(len(target) - 2)))
        if not trigrams:
            return []
        expr = " OR ".join('"' + t.replace('"', '""') + '"' for t in trigrams[:16])
        try:
            rows = self._conn().execute(
                "SELECT key, name FROM key_trigrams WHERE key MATCH ? "
                "ORDER BY rank LIMIT ?",
                (expr, limit),
            ).fetchall()
        except sqlite3.Error:
            return []
        return [(r["key"], r["name"]) for r in rows]

    def iter_meta(self) -> Iterator[dict]:
        """Stream every catalog metadata dict (used by /api/by-type)."""
        if not self._ready:
            return
        try:
            for row in self._conn().execute("SELECT meta_json FROM events"):
                try:
                    yield json.loads(row["meta_json"])
                except json.JSONDecodeError:
                    continue
        except sqlite3.Error:
            return

    def query(
        self,
        q: str = "",
        type_filter: str = "",
        has_spectra: bool | None = None,
        has_photometry: bool | None = None,
        sort: str = "discoverdate",
        order: str = "desc",
        page: int = 1,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Indexed multi-criteria search with SQL-side filtering and sorting."""
        limit = max(1, min(int(limit), 250))
        page = max(1, int(page))
        reverse = str(order).lower() == "desc"

        where: list[str] = []
        params: list[Any] = []

        q_clean = (q or "").strip().lower()
        if q_clean:
            where.append("search_blob LIKE ?")
            params.append(f"%{q_clean}%")

        type_clean = (type_filter or "").strip().lower()
        if type_clean and type_clean not in ("all", "any"):
            if type_clean == "ia":
                where.append("(type LIKE '%ia%' OR type LIKE '%i-a%')")
            elif type_clean == "ii":
                where.append("type LIKE '%ii%'")
            elif type_clean in ("ibc", "ib/c"):
                where.append("(type LIKE '%ib%' OR type LIKE '%ic%')")
            elif type_clean == "slsn":
                where.append("(type LIKE '%slsn%' OR type LIKE '%superluminous%')")
            elif type_clean == "tde":
                where.append("(type LIKE '%tde%' OR type LIKE '%tidal%')")
            else:
                where.append("type LIKE ?")
                params.append(f"%{type_clean}%")

        if has_spectra is True:
            where.append("spec > 0")
        elif has_spectra is False:
            where.append("spec = 0")
        if has_photometry is True:
            where.append("phot > 0")
        elif has_photometry is False:
            where.append("phot = 0")

        where_sql = (" WHERE " + " AND ".join(where)) if where else ""

        sort_key = str(sort).lower()
        direction = "DESC" if reverse else "ASC"
        if sort_key in ("discoverdate", "date"):
            order_sql = f"sort_date {direction}, name ASC"
        elif sort_key == "name":
            order_sql = f"name COLLATE NOCASE {direction}"
        elif sort_key in ("claimedtype", "type"):
            order_sql = f"type COLLATE NOCASE {direction}"
        elif sort_key in ("redshift", "z"):
            # NULLs last in both directions, matching the in-memory behaviour.
            order_sql = f"(z IS NULL) ASC, z {direction}"
        elif sort_key in ("maxappmag", "mag"):
            order_sql = f"(mag IS NULL) ASC, mag {direction}"
        elif sort_key in ("spectralink", "spec"):
            order_sql = f"spec {direction}"
        elif sort_key in ("photolink", "phot"):
            order_sql = f"phot {direction}"
        else:
            order_sql = f"sort_date {direction}"

        try:
            conn = self._conn()
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM events{where_sql}", params
            ).fetchone()
            total_n = int(total["n"]) if total else 0
            pages = max(1, -(-total_n // limit))
            page = min(page, pages)
            offset = (page - 1) * limit
            rows = conn.execute(
                f"SELECT * FROM events{where_sql} ORDER BY {order_sql} "
                f"LIMIT ? OFFSET ?",
                params + [limit, offset],
            ).fetchall()
        except sqlite3.Error as exc:
            print(f"[CatalogStore] query failed: {exc}", flush=True)
            return {
                "total": 0, "page": 1, "limit": limit, "pages": 1,
                "has_next": False, "has_prev": False, "items": [],
            }

        items = []
        for row in rows:
            try:
                aliases = json.loads(row["aliases_json"])
            except json.JSONDecodeError:
                aliases = []
            items.append({
                "name": row["name"],
                "aliases": aliases,
                "type": row["type"],
                "type_badge": row["type_badge"],
                "date": row["date"],
                "age": row["age"],
                "mag": row["mag"],
                "z": row["z"],
                "ra": row["ra"],
                "dec": row["dec"],
                "host": row["host"],
                "disc": row["disc"],
                "spec": row["spec"],
                "phot": row["phot"],
                "search_blob": row["search_blob"],
            })

        return {
            "total": total_n,
            "page": page,
            "limit": limit,
            "pages": pages,
            "has_next": page < pages,
            "has_prev": page > 1,
            "items": items,
        }

    def stats(self) -> dict[str, Any]:
        if not self._ready:
            return {"ready": False, "events": 0}
        try:
            rows = {
                r["key"]: r["value"]
                for r in self._conn().execute("SELECT key, value FROM meta")
            }
        except sqlite3.Error:
            rows = {}
        try:
            size = self.db_path.stat().st_size
        except OSError:
            size = 0
        return {
            "ready": True,
            "events": rows.get("event_count"),
            "built_at": rows.get("built_at"),
            "schema_version": rows.get("schema_version"),
            "overlay_mtime": rows.get("overlay_mtime"),
            "db_bytes": size,
            "db_path": str(self.db_path),
        }

    def upsert_catalog_items(self, items: Iterable[dict[str, Any]]) -> int:
        """Incrementally replace catalog rows without a full 110k rebuild.

        Opens a short-lived read-write connection (WAL). Thread-local read
        handles are dropped afterward so the next lookup sees new rows.
        Idempotent: re-upserting the same items yields the same rows.
        """
        rows_in: list[tuple] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            row = _row_from_catalog_item(item)
            if row is not None:
                rows_in.append(row)
        if not rows_in:
            return 0

        with self._build_lock:
            if not self.db_path.is_file():
                # No base index yet — caller should build() first.
                return 0
            conn = sqlite3.connect(str(self.db_path), timeout=60.0)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                fts_enabled = False
                try:
                    conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='key_trigrams'"
                    ).fetchone()
                    fts_enabled = True
                except sqlite3.Error:
                    fts_enabled = False

                for row in rows_in:
                    name = row[0]
                    conn.execute("DELETE FROM keys WHERE name = ?", (name,))
                    conn.execute("DELETE FROM key_lengths WHERE name = ?", (name,))
                    if fts_enabled:
                        try:
                            conn.execute("DELETE FROM key_trigrams WHERE name = ?", (name,))
                        except sqlite3.Error:
                            pass
                    conn.execute(
                        "INSERT OR REPLACE INTO events VALUES "
                        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        row,
                    )
                    key_rows: set[tuple[str, str]] = set()
                    for k in (_norm_key(name), _norm_key(name).replace(" ", "")):
                        if k:
                            key_rows.add((k, name))
                    for alias in json.loads(row[1]):
                        ak = _norm_key(alias)
                        if ak:
                            key_rows.add((ak, name))
                            key_rows.add((ak.replace(" ", ""), name))
                    for k, n in sorted(key_rows):
                        conn.execute(
                            "INSERT OR REPLACE INTO keys(key, name) VALUES (?,?)", (k, n)
                        )
                        conn.execute(
                            "INSERT OR REPLACE INTO key_lengths(key, name, length) "
                            "VALUES (?,?,?)",
                            (k, n, len(k)),
                        )
                        if fts_enabled and len(k) >= 3:
                            try:
                                conn.execute(
                                    "INSERT INTO key_trigrams(key, name) VALUES (?,?)",
                                    (k, n),
                                )
                            except sqlite3.Error:
                                pass

                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('overlay_mtime', ?)",
                    (str(time.time()),),
                )
                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES ('built_at', ?)",
                    (str(int(time.time())),),
                )
                # Keep event_count as max(existing, distinct names) — upserts
                # of existing rows must not inflate the counter.
                try:
                    n = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                    conn.execute(
                        "INSERT OR REPLACE INTO meta VALUES ('event_count', ?)",
                        (str(int(n)),),
                    )
                except sqlite3.Error:
                    pass
                conn.commit()
            finally:
                conn.close()

            self._ready = True
            self.close()  # force readers to reopen
            return len(rows_in)
