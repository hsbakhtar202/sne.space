"""Resolve the on-disk data root for ingested event JSON.

The event JSON corpus is the only stateful thing sne.space owns. Everything
else (rendered HTML cache, SQLite index, gzip mirrors) is derived and safe to
rebuild. This module is the single place that decides where the corpus lives so
that a container mount and a local checkout agree.

Resolution order, first hit wins:

1. ``SNE_DATA_DIR`` environment variable, if set and non-empty.
2. ``<repo>/serve/www/astrocats/astrocats/supernovae/output`` when it already
   contains event subdirectories (the local development / baked-image case).
3. ``/data/astrocats/supernovae/output`` when ``/data`` is a mounted volume.

The historical URL prefix ``/astrocats/astrocats/supernovae/output/`` is kept so
existing links and the static-file handler keep working; only the filesystem
root behind it moves.
"""

from __future__ import annotations

import os
from pathlib import Path

# Historical, externally visible URL prefix. Do not change: it is baked into
# links, sitemaps, and third-party references.
URL_PREFIX = "astrocats/astrocats/supernovae/output"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WWW = _REPO_ROOT / "serve" / "www"
_BAKED_OUTPUT = _WWW / URL_PREFIX

# Container mount point used by docker-compose.yml.
_MOUNT_OUTPUT = Path("/data/astrocats/supernovae/output")

_EPOCH_DIRS = (
    "sne-pre-1990",
    "sne-1990-1999",
    "sne-2000-2004",
    "sne-2005-2009",
    "sne-2010-2014",
    "sne-2015-2019",
    "sne-2020-2024",
    "sne-2025-2029",
)


def _looks_like_corpus(path: Path) -> bool:
    """True when ``path`` holds at least one epoch directory of event JSON."""
    try:
        if not path.is_dir():
            return False
        return any((path / d).is_dir() for d in _EPOCH_DIRS)
    except OSError:
        return False


def _candidate_roots() -> list[Path]:
    """Roots to *search* for an existing corpus, most authoritative first."""
    roots: list[Path] = []
    env = (os.environ.get("SNE_DATA_DIR") or "").strip()
    if env:
        roots.append(Path(env).expanduser())
    roots.append(_BAKED_OUTPUT)
    roots.append(_MOUNT_OUTPUT)
    return roots


def resolve_output_dir() -> Path:
    """Return the writable event-corpus root, creating the mount path if needed.

    An explicit ``SNE_DATA_DIR`` is honoured *unconditionally*. Gating it behind
    ``_looks_like_corpus`` was a bug: a freshly created volume is empty by
    definition, so the very first boot after mounting durable storage silently
    fell back to the baked image path and wrote there instead. The mount looked
    configured while every write still went to the ephemeral layer.
    """
    env = (os.environ.get("SNE_DATA_DIR") or "").strip()
    if env:
        root = Path(env).expanduser()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return root

    for cand in (_BAKED_OUTPUT, _MOUNT_OUTPUT):
        if _looks_like_corpus(cand):
            return cand
    # Nothing pre-populated: prefer the container mount when it exists as a
    # directory, otherwise fall back to the baked-in tree.
    mount_parent = _MOUNT_OUTPUT.parent.parent
    if mount_parent.is_dir() or Path("/data").is_dir():
        _MOUNT_OUTPUT.mkdir(parents=True, exist_ok=True)
        return _MOUNT_OUTPUT
    _BAKED_OUTPUT.mkdir(parents=True, exist_ok=True)
    return _BAKED_OUTPUT


OUTPUT_DIR = resolve_output_dir()

# Directory the HTTP layer serves ``/astrocats/astrocats/supernovae/output/...``
# from. Equals OUTPUT_DIR for a baked image; for a mounted volume the static
# handler resolves through here so URLs stay stable.
STATIC_OUTPUT_DIR = _BAKED_OUTPUT


# ---------------------------------------------------------------------------
# Runtime data: the small JSON files that ingest rewrites and the homepage reads
# ---------------------------------------------------------------------------
# ``recent-events.json`` and ``recent-catalog.min.json`` are *produced at runtime*
# by ingest and *consumed* by the homepage. Historically they lived in
# ``serve/www/assets/`` next to the CSS and JavaScript. That directory is part of
# the image, so every redeploy reset these files to their build-time contents and
# the homepage silently served a stale recent-list until ingest happened to run.
#
# The fix is a dedicated runtime directory rather than mounting ``assets/`` as a
# volume: mounting the whole public assets tree would shadow version-controlled
# CSS/JS behind whatever an old volume happened to contain. Only the two mutable
# JSON files move; static assets stay in the image where they belong.

_RUNTIME_ASSETS_BAKED = _WWW / "assets"

# Container mount point used by docker-compose.yml for mutable runtime JSON.
_MOUNT_RUNTIME = Path("/data/sne-runtime")

RUNTIME_ASSET_FILES = ("recent-events.json", "recent-catalog.min.json")


def _looks_like_runtime_dir(path: Path) -> bool:
    try:
        return path.is_dir() and any((path / n).is_file() for n in RUNTIME_ASSET_FILES)
    except OSError:
        return False


def resolve_runtime_dir() -> Path:
    """Return the writable directory holding mutable runtime JSON.

    Resolution order, first hit wins:

    1. ``SNE_RUNTIME_DIR`` — honoured unconditionally when set and non-empty, so
       a mounted volume always wins over the image's baked copy. This mirrors the
       ``SNE_DATA_DIR`` rule: gating a mount behind a "does it look populated"
       check breaks the very first boot, when the volume is empty by definition.
    2. ``/data/sne-runtime`` when ``/data`` exists (the container mount case).
    3. ``serve/www/assets`` (local development and baked-image fallback).

    The returned path is created if missing; failure is non-fatal so a read-only
    filesystem degrades to the baked directory instead of crashing the server.
    """
    env = (os.environ.get("SNE_RUNTIME_DIR") or "").strip()
    candidates: list[Path] = []
    if env:
        candidates.append(Path(env).expanduser())
    if Path("/data").is_dir():
        candidates.append(_MOUNT_RUNTIME)
    candidates.append(_RUNTIME_ASSETS_BAKED)

    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        if os.access(cand, os.W_OK):
            return cand
    return _RUNTIME_ASSETS_BAKED


RUNTIME_DIR = resolve_runtime_dir()


def runtime_asset_path(name: str) -> Path:
    """Absolute path for one mutable runtime JSON file.

    Falls back to the baked assets copy when the runtime directory does not hold
    the file yet, so a first boot that has not seeded or ingested still serves the
    image's copy instead of rendering an empty recent-list.
    """
    target = RUNTIME_DIR / name
    if target.is_file():
        return target
    baked = _RUNTIME_ASSETS_BAKED / name
    if baked.is_file():
        return baked
    return target


def runtime_write_path(name: str) -> Path:
    """Absolute path producers must write to — always the persistent directory.

    Deliberately different from ``runtime_asset_path()``: readers may fall back to
    the baked copy when the runtime file is absent, but a *writer* must never write
    into the image layer. Writing to ``RUNTIME_DIR`` unconditionally is what makes
    the mount authoritative; falling back would reintroduce the redeploy data loss
    this exists to prevent.
    """
    try:
        RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return RUNTIME_DIR / name


def seed_runtime_assets() -> list[str]:
    """Copy baked runtime JSON into the persistent directory when absent.

    Never overwrites: an existing file is authoritative because it reflects real
    ingested data, while the baked copy is a build-time snapshot. Returns the
    names actually copied, for the entrypoint/boot log.
    """
    copied: list[str] = []
    for name in RUNTIME_ASSET_FILES:
        src = _RUNTIME_ASSETS_BAKED / name
        dst = RUNTIME_DIR / name
        if not src.is_file():
            continue
        try:
            if dst.is_file():
                continue
            tmp = dst.with_name(f".{dst.name}.seed.{os.getpid()}")
            tmp.write_bytes(src.read_bytes())
            os.replace(tmp, dst)
            copied.append(name)
        except OSError:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
    return copied


def url_to_path(url_path: str) -> Path | None:
    """Map a request path under URL_PREFIX onto the resolved corpus root.

    Returns ``None`` when the path is not under the prefix. The returned path is
    not guaranteed to exist; callers must check.
    """
    prefix = "/" + URL_PREFIX + "/"
    if not url_path.startswith(prefix):
        return None
    rest = url_path[len(prefix):].lstrip("/")
    if not rest:
        return None
    # Reject traversal attempts before touching the filesystem.
    parts = [p for p in rest.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    return OUTPUT_DIR.joinpath(*parts)


def ensure_static_link() -> None:
    """Expose the resolved corpus root under the historical WWW URL prefix.

    When ``SNE_DATA_DIR`` points outside ``serve/www`` the static handler still
    needs ``serve/www/astrocats/.../output`` to exist. A symlink keeps one copy of
    the bytes while preserving the public URL layout.
    """
    try:
        if STATIC_OUTPUT_DIR.exists() and not STATIC_OUTPUT_DIR.is_symlink():
            if _looks_like_corpus(STATIC_OUTPUT_DIR) and STATIC_OUTPUT_DIR.resolve() != OUTPUT_DIR.resolve():
                # A real baked tree already exists; leave it alone rather than
                # shadowing it. Mixed trees are handled by the explicit
                # SNE_DATA_DIR path in resolve_output_dir().
                return
        if STATIC_OUTPUT_DIR.is_symlink():
            if STATIC_OUTPUT_DIR.resolve() == OUTPUT_DIR.resolve():
                return
            STATIC_OUTPUT_DIR.unlink()
        STATIC_OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
        STATIC_OUTPUT_DIR.symlink_to(OUTPUT_DIR, target_is_directory=True)
    except OSError:
        # Symlinks are unavailable on some volume drivers; URL mapping in
        # url_to_path() still covers the mounted case.
        return
