#!/usr/bin/env python3
"""Home Assistant Cleanup Tool.

Interactive menu for various cleanup operations.

Features:
  - Remove orphaned entities (missing device/config/automation/script/scene)
  - Fix numeric suffix issues (_2, _3, etc.) on entity IDs
  - Clean deleted_entities and deleted_devices from registries
  - Purge old states/events and vacuum database
  - Restore entities from backup files (selective or full restore)
  - Auto-detects recorder purge_keep_days from HA config
  - Auto-detects config path (HAOS, Docker, Core)

Usage:
  python3 ha-cleanup.py              # Interactive menu
  python3 ha-cleanup.py --dry-run    # Preview all changes
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

VERSION = "1.6.0"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

# Auto-detect config path
CONFIG_PATHS: list[str | Path] = [
    "/homeassistant",
    "/config",
    Path.home() / ".homeassistant",
]
_config_path: Path | None = next(
    (Path(p) for p in CONFIG_PATHS if Path(p).exists()), None,
)

if not _config_path:
    logger.error("Could not find Home Assistant config directory")
    sys.exit(1)

CONFIG_PATH: Path = _config_path

# Registry paths
ENTITY_REGISTRY = CONFIG_PATH / ".storage/core.entity_registry"
DEVICE_REGISTRY = CONFIG_PATH / ".storage/core.device_registry"
CONFIG_ENTRIES = CONFIG_PATH / ".storage/core.config_entries"

# Database
DB_PATH = CONFIG_PATH / "home-assistant_v2.db"

# Storage paths
STORAGE_PATH = CONFIG_PATH / ".storage"

# YAML config paths
AUTOMATION_PATH = CONFIG_PATH / "automation"
SCRIPT_PATH = CONFIG_PATH / "scripts"
SCENE_PATH = CONFIG_PATH / "scenes"

# Defaults
DEFAULT_PURGE_DAYS = 14
BACKUP_RETENTION_DAYS = 7
ENTITY_COUNT_DIFF_WARNING_THRESHOLD = 50  # Warn if backup differs by >50%
HA_STOP_WAIT_SECONDS = 5

# Database purge — adaptive batch sizes
BATCH_SIZE_SMALL = 10_000      # < 100K rows
BATCH_SIZE_MEDIUM = 50_000     # 100K - 1M rows
BATCH_SIZE_LARGE = 100_000     # > 1M rows
BATCH_THRESHOLD_MEDIUM = 100_000    # rows — switch from SMALL to MEDIUM
BATCH_THRESHOLD_LARGE = 1_000_000   # rows — switch from MEDIUM to LARGE

# Database purge — SQLite PRAGMA optimization
PRAGMA_CACHE_SIZE = -64_000       # 64 MB cache (negative = KiB)
PRAGMA_MMAP_SIZE = 268_435_456    # 256 MB memory-mapped I/O

# Database purge — VACUUM
VACUUM_SPACE_SAFETY_MARGIN = 1.1          # 10% safety margin
VACUUM_SPEED_ESTIMATE_MB_PER_SEC = 100.0  # rough SSD estimate for ETA

# Regex patterns (compiled at module level for performance)
NUMERIC_SUFFIX_PATTERN = re.compile(r"_(\d+)$")
YAML_ID_PATTERN = re.compile(r'(?:^|\n)\s*-?\s*id:\s*["\']?([^"\'\n\r]+)["\']?')
BACKUP_PATTERN = re.compile(r"\.backup\.(\d{8}_\d{6})(?:_\d+)?$")
DUPLICATE_SUFFIX_PATTERN = re.compile(r"_([2-9]|\d{2,})$")


# ============================================================
# Data Structures
# ============================================================

@dataclass
class BackupInfo:
    """Backup file metadata."""

    path: Path
    timestamp: datetime
    file_type: str  # "entity_registry" or "device_registry"
    size_mb: float
    entity_count: int


@dataclass
class EntityDiff:
    """Difference between backup and current registry."""

    deleted: list[dict[str, Any]]      # In backup but not in current
    new: list[dict[str, Any]]          # In current but not in backup
    modified: list[tuple[dict[str, Any], dict[str, Any]]]  # (backup, current)


class _DbCtx(NamedTuple):
    """Grouped SQLite connection + cursor for DB purge helpers."""

    cur: sqlite3.Cursor
    conn: sqlite3.Connection


class _TableRef(NamedTuple):
    """Reference to a (table, column) pair in the DB."""

    table: str
    column: str


# ============================================================
# Simple Cache for JSON files
# ============================================================

_json_cache: dict[Path, tuple[float, dict[str, Any]]] = {}  # path -> (mtime, data)


def _get_cached_json(path: Path) -> dict[str, Any] | None:
    """Get cached JSON if file hasn't changed."""
    if path not in _json_cache:
        return None

    try:
        current_mtime = path.stat().st_mtime
        cached_mtime, cached_data = _json_cache[path]
        if current_mtime == cached_mtime:
            return cached_data
    except OSError:
        pass

    return None


def _cache_json(path: Path, data: dict[str, Any]) -> None:
    """Cache JSON data with file mtime."""
    try:
        mtime = path.stat().st_mtime
        _json_cache[path] = (mtime, data)
    except OSError:
        pass


def invalidate_cache(path: Path | None = None) -> None:
    """Invalidate JSON cache for specific path or all."""
    if path:
        _json_cache.pop(path, None)
    else:
        _json_cache.clear()


# ============================================================
# Utility Functions
# ============================================================

def log(msg: str) -> None:
    """Log a message with timestamp."""
    logger.info(msg)


def backup_file(path: Path) -> Path:
    """Create a timestamped backup of a file."""
    if not path.exists():
        msg = f"Cannot backup non-existent file: {path}"
        raise FileNotFoundError(msg)
    stamp = datetime.now(tz=None).strftime("%Y%m%d_%H%M%S")  # noqa: DTZ005 — local time intentional
    backup = Path(f"{path}.backup.{stamp}")
    # Guard against sub-second collisions when backups fire back-to-back
    counter = 1
    while backup.exists():
        backup = Path(f"{path}.backup.{stamp}_{counter}")
        counter += 1
    shutil.copy2(path, backup)
    return backup


def load_json(path: Path, use_cache: bool = True) -> dict[str, Any]:
    """Load JSON file with error handling and optional caching."""
    if not path.exists():
        msg = f"File not found: {path}"
        raise FileNotFoundError(msg)

    # Check cache first
    if use_cache:
        cached = _get_cached_json(path)
        if cached is not None:
            return cached

    try:
        with path.open(encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
            if use_cache:
                _cache_json(path, data)
            return data
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON in {path}: {e}"
        raise ValueError(msg) from e


def save_json(path: Path, data: dict[str, Any]) -> None:
    """Save data to JSON file with atomic write and file locking.

    This prevents race conditions when HA might be writing to the same file.
    Uses a temporary file + atomic rename pattern.
    """
    temp_path = Path(f"{path}.tmp.{os.getpid()}")

    try:
        with temp_path.open("w", encoding="utf-8") as f:
            # Acquire exclusive lock (blocks if HA is writing)
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

        # Preserve original file permissions
        try:
            original_mode = path.stat().st_mode
        except OSError:
            original_mode = None

        # Atomic rename (POSIX guarantees atomicity)
        temp_path.replace(path)

        # Restore permissions if we had them
        if original_mode is not None:
            path.chmod(original_mode)

        # Invalidate cache after write
        invalidate_cache(path)

    except Exception as e:
        # Clean up temp file on error
        if temp_path.exists():
            temp_path.unlink()
        msg = f"Failed to save JSON to {path}: {e}"
        raise ValueError(msg) from e


def get_db_size() -> float:
    """Get database size in MB."""
    if DB_PATH.exists():
        return DB_PATH.stat().st_size / (1024 * 1024)
    return 0.0


def _run_ha_command(cmd: list[str]) -> bool:
    """Run an HA lifecycle command. Returns True on success.

    The cmd list is always a hardcoded literal from stop_ha/start_ha —
    no user input ever reaches subprocess.
    """
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)  # noqa: S603 — cmd is hardcoded
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        return False
    return True


def stop_ha() -> str | None:
    """Stop Home Assistant using available method."""
    methods = [
        (["ha", "core", "stop"], "ha"),
        (["systemctl", "stop", "home-assistant@homeassistant"], "systemctl"),
        (["docker", "stop", "homeassistant"], "docker"),
    ]
    for cmd, method in methods:
        if _run_ha_command(cmd):
            return method
    return None


def start_ha(method: str) -> bool:
    """Start Home Assistant using specified method."""
    cmds = {
        "ha": ["ha", "core", "start"],
        "systemctl": ["systemctl", "start", "home-assistant@homeassistant"],
        "docker": ["docker", "start", "homeassistant"],
    }
    if method not in cmds:
        return False
    return _run_ha_command(cmds[method])


@contextmanager
def ha_stopped() -> Generator[str | None]:
    """Context manager to stop and restart HA around operations.

    Yields the stop method string (or None if manual stop).
    Ensures HA is restarted in the finally block.
    """
    method = stop_ha()
    if not method:
        log("⚠️  Could not stop HA automatically.")
        if not confirm_action("Please stop HA manually. Continue when stopped?"):
            msg = "HA not stopped — operation aborted"
            raise RuntimeError(msg)

    time.sleep(HA_STOP_WAIT_SECONDS)
    try:
        yield method
    finally:
        invalidate_cache()
        log("Starting Home Assistant...")
        if method:
            if not start_ha(method):
                log("⚠️  Failed to start HA. Please start manually.")
        else:
            log("Please start Home Assistant manually.")


def _extract_purge_keep_days(yaml_content: str) -> int | None:
    """Parse `recorder: ... purge_keep_days: N` from YAML, respecting indentation.

    Matches only keys inside the recorder block (indented deeper than
    `recorder:` itself, stopping at the next top-level key).
    """
    lines = yaml_content.splitlines()
    in_recorder = False
    recorder_indent = -1

    for line in lines:
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(stripped)

        if not in_recorder:
            if stripped.startswith("recorder:") and indent == 0:
                in_recorder = True
                recorder_indent = 0
            continue

        # Inside recorder — exit when we hit another top-level key
        if indent <= recorder_indent:
            break

        match = re.match(r"purge_keep_days:\s*(\d+)", stripped)
        if match:
            return int(match.group(1))

    return None


def get_recorder_purge_days() -> int:
    """Get purge_keep_days from HA recorder config, fallback to default."""
    # Try configuration.yaml first
    config_yaml = CONFIG_PATH / "configuration.yaml"
    if config_yaml.exists():
        try:
            content = config_yaml.read_text(encoding="utf-8")
            days = _extract_purge_keep_days(content)
            if days is not None:
                return days
        except OSError:
            pass

    # Try .storage/core.config_entries for recorder integration
    if CONFIG_ENTRIES.exists():
        try:
            data = load_json(CONFIG_ENTRIES)
            for entry in data.get("data", {}).get("entries", []):
                if entry.get("domain") == "recorder":
                    options = entry.get("options", {})
                    if "purge_keep_days" in options:
                        return int(options["purge_keep_days"])
        except (FileNotFoundError, ValueError, KeyError):
            pass

    return DEFAULT_PURGE_DAYS


# ============================================================
# ID Collection Functions
# ============================================================

def extract_ids_from_yaml_file(path: Path) -> set[str]:
    """Extract IDs from a YAML file using regex."""
    ids: set[str] = set()
    if not path.exists():
        return ids

    try:
        content = path.read_text(encoding="utf-8")
        # Use pre-compiled pattern
        for match in YAML_ID_PATTERN.finditer(content):
            id_value = match.group(1).strip()
            if id_value and not id_value.startswith("#"):
                ids.add(id_value)
    except OSError:
        pass

    return ids


def get_entity_ids(
    _entity_type: str,
    folder_path: Path,
    yaml_file: str,
    storage_file: str,
) -> set[str]:
    """Get entity IDs from YAML files and UI storage.

    Args:
        _entity_type: Type of entity (automation, script, scene) — reserved
        folder_path: Path to folder containing YAML files
        yaml_file: Name of root YAML file (e.g., "automations.yaml")
        storage_file: Name of storage file (e.g., "automations")

    Returns:
        Set of entity IDs

    """
    ids: set[str] = set()

    # Check folder
    if folder_path.exists():
        for f in folder_path.glob("*.yaml"):
            ids.update(extract_ids_from_yaml_file(f))

    # Check root YAML file
    root_yaml = CONFIG_PATH / yaml_file
    ids.update(extract_ids_from_yaml_file(root_yaml))

    # Check UI-based storage
    ui_storage = STORAGE_PATH / storage_file
    if ui_storage.exists():
        try:
            data = load_json(ui_storage)
            for item in data.get("data", {}).get("items", []):
                if item.get("id"):
                    ids.add(item["id"])
        except (FileNotFoundError, ValueError, KeyError):
            pass

    return ids


def get_automation_ids() -> set[str]:
    """Get all automation IDs from YAML files and UI storage."""
    return get_entity_ids(
        "automation", AUTOMATION_PATH, "automations.yaml", "automations",
    )


def get_script_ids() -> set[str]:
    """Get all script IDs from YAML files and UI storage."""
    return get_entity_ids("script", SCRIPT_PATH, "scripts.yaml", "scripts")


def get_scene_ids() -> set[str]:
    """Get all scene IDs from YAML files and UI storage."""
    return get_entity_ids("scene", SCENE_PATH, "scenes.yaml", "scenes")


# ============================================================
# Cleanup Functions
# ============================================================

def _is_entity_orphan(
    entity: dict[str, Any],
    devices: set[str],
    config_entries: set[str],
    definition_ids: dict[str, set[str]],
) -> bool:
    """Check if a single entity dict is orphaned.

    definition_ids maps platform ("automation"/"script"/"scene") to the set
    of valid IDs for that platform.
    """
    device_id = entity.get("device_id")
    if device_id and device_id not in devices:
        return True

    config_entry_id = entity.get("config_entry_id")
    if config_entry_id and config_entry_id not in config_entries:
        return True

    platform = entity.get("platform", "")
    unique_id = entity.get("unique_id")
    valid_ids = definition_ids.get(platform)
    return bool(valid_ids is not None and unique_id and unique_id not in valid_ids)


def find_orphaned_entities() -> list[tuple[str, str, str]]:
    """Find entities with missing device, config_entry, or definition.

    Returns list of tuples: (platform, entity_id, name)
    """
    # Check required files exist
    for registry, label in (
        (ENTITY_REGISTRY, "Entity registry"),
        (DEVICE_REGISTRY, "Device registry"),
        (CONFIG_ENTRIES, "Config entries"),
    ):
        if not registry.exists():
            log(f"⚠️  {label} not found, skipping orphan detection")
            return []

    try:
        entity_data = load_json(ENTITY_REGISTRY)
        device_data = load_json(DEVICE_REGISTRY)
        config_data = load_json(CONFIG_ENTRIES)
    except (FileNotFoundError, ValueError) as e:
        log(f"⚠️  Error loading registry files: {e}")
        return []

    devices = {
        d["id"] for d in device_data.get("data", {}).get("devices", [])
    }
    config_entries = {
        e["entry_id"] for e in config_data.get("data", {}).get("entries", [])
    }
    definition_ids = {
        "automation": get_automation_ids(),
        "script": get_script_ids(),
        "scene": get_scene_ids(),
    }

    return [
        (
            entity.get("platform", ""),
            entity.get("entity_id", ""),
            entity.get("original_name", ""),
        )
        for entity in entity_data.get("data", {}).get("entities", [])
        if _is_entity_orphan(entity, devices, config_entries, definition_ids)
    ]


def cleanup_orphaned_entities(dry_run: bool = False) -> int:
    """Remove orphaned entities from registry."""
    orphans = find_orphaned_entities()

    if not orphans:
        log("✓ No orphaned entities found")
        return 0

    if dry_run:
        log(f"Found {len(orphans)} orphaned entities:")
        for platform, eid, name in sorted(orphans):
            log(f"  - {platform}: {eid} ({name})")
        return len(orphans)

    # Backup before modification
    backup_file(ENTITY_REGISTRY)

    orphan_eids = {o[1] for o in orphans}
    data = load_json(ENTITY_REGISTRY, use_cache=False)
    original_count = len(data["data"]["entities"])
    data["data"]["entities"] = [
        e for e in data["data"]["entities"]
        if e.get("entity_id") not in orphan_eids
    ]
    new_count = len(data["data"]["entities"])

    save_json(ENTITY_REGISTRY, data)
    log(f"✓ Removed {original_count - new_count} orphaned entities")
    return original_count - new_count


def cleanup_deleted_items(dry_run: bool = False) -> int:
    """Clean deleted items from entity and device registries."""
    count = 0

    registries = [
        (ENTITY_REGISTRY, "deleted_entities"),
        (DEVICE_REGISTRY, "deleted_devices"),
    ]

    for path, key in registries:
        if not path.exists():
            continue

        try:
            data = load_json(path)
        except (FileNotFoundError, ValueError) as e:
            log(f"⚠️  Error loading {path}: {e}")
            continue

        deleted_items = data.get("data", {}).get(key, [])
        n = len(deleted_items)

        if n > 0:
            if dry_run:
                log(f"Would clean {n} {key.replace('_', ' ')}")
            else:
                backup_file(path)
                data["data"][key] = []
                save_json(path, data)
                log(f"✓ Cleaned {n} {key.replace('_', ' ')}")
            count += n

    if count == 0:
        log("✓ No deleted registry items to clean")

    return count


# ============================================================
# Database Purge Helpers
# ============================================================

def _get_batch_size(total_rows: int) -> int:
    """Get optimal batch size based on total row count.

    Returns adaptive batch size:
      - < 100K rows  -> BATCH_SIZE_SMALL  (10,000)
      - 100K-1M rows -> BATCH_SIZE_MEDIUM (50,000)
      - > 1M rows    -> BATCH_SIZE_LARGE  (100,000)
    """
    if total_rows < BATCH_THRESHOLD_MEDIUM:
        return BATCH_SIZE_SMALL
    if total_rows < BATCH_THRESHOLD_LARGE:
        return BATCH_SIZE_MEDIUM
    return BATCH_SIZE_LARGE


def _log_phase_start(phase: str) -> float:
    """Log phase start and return monotonic timestamp."""
    log(f"  [{phase}] Starting...")
    return time.monotonic()


def _log_phase_end(phase: str, start_time: float, detail: str = "") -> None:
    """Log phase completion with elapsed time."""
    elapsed = time.monotonic() - start_time
    suffix = f" — {detail}" if detail else ""
    log(f"  [{phase}] Done in {elapsed:.1f}s{suffix}")


def _configure_pragmas(conn: sqlite3.Connection) -> dict[str, Any]:
    """Set optimized PRAGMAs for purge operations.

    Returns dict of original values for restoration.
    """
    originals: dict[str, Any] = {}

    for pragma, new_value in (
        ("cache_size", PRAGMA_CACHE_SIZE),
        ("temp_store", "MEMORY"),
        ("mmap_size", PRAGMA_MMAP_SIZE),
    ):
        row = conn.execute(f"PRAGMA {pragma}").fetchone()
        originals[pragma] = row[0] if row else 0
        conn.execute(f"PRAGMA {pragma} = {new_value}")

    return originals


def _restore_pragmas(
    conn: sqlite3.Connection,
    originals: dict[str, Any],
) -> None:
    """Restore PRAGMAs to original values (best-effort)."""
    for pragma, value in originals.items():
        with contextlib.suppress(sqlite3.Error):
            conn.execute(f"PRAGMA {pragma} = {value}")


def _ensure_index(
    cur: sqlite3.Cursor,
    conn: sqlite3.Connection,
    table: str,
    column: str,
) -> bool:
    """Create a temporary index if one does not already exist on column.

    Returns True if a new index was created, False if one already existed.
    """
    cur.execute(f"PRAGMA index_list({table})")
    for idx_info in cur.fetchall():
        idx_name = idx_info[1]
        cur.execute(f"PRAGMA index_info({idx_name})")
        cols = [row[2] for row in cur.fetchall()]
        if column in cols:
            return False  # Index already exists

    idx_name = f"ix_tmp_{table}_{column}"
    log(f"    Creating temporary index {idx_name}...")
    cur.execute(
        f"CREATE INDEX {idx_name} ON {table} ({column}) "
        f"WHERE {column} IS NOT NULL",
    )
    conn.commit()
    return True


def _drop_temp_index(
    cur: sqlite3.Cursor,
    conn: sqlite3.Connection,
    table: str,
    column: str,
) -> None:
    """Drop a temporary index (best-effort)."""
    idx_name = f"ix_tmp_{table}_{column}"
    try:
        cur.execute(f"DROP INDEX IF EXISTS {idx_name}")
        conn.commit()
    except sqlite3.Error:
        pass  # Best effort


def _count_purgeable(
    cur: sqlite3.Cursor,
    cutoff_ts: int,
) -> tuple[int, int]:
    """Count purgeable states and events older than cutoff."""
    cur.execute(
        "SELECT COUNT(*) FROM states WHERE last_updated_ts < ?",
        (cutoff_ts,),
    )
    states: int = cur.fetchone()[0]

    cur.execute(
        "SELECT COUNT(*) FROM events WHERE time_fired_ts < ?",
        (cutoff_ts,),
    )
    events: int = cur.fetchone()[0]

    return (states, events)


def _batch_delete_table(
    db: _DbCtx,
    target: _TableRef,
    cutoff_ts: int,
    total: int,
    batch_size: int,
) -> int:
    """Batch delete rows older than cutoff from a table.

    Returns total deleted count.
    """
    total_deleted = 0
    batch_num = 0
    total_batches = (total + batch_size - 1) // batch_size  # ceil division

    while True:
        batch_num += 1
        db.cur.execute(
            f"DELETE FROM {target.table} WHERE rowid IN ("
            f"  SELECT rowid FROM {target.table}"
            f"  WHERE {target.column} < ? LIMIT ?"
            ")",
            (cutoff_ts, batch_size),
        )
        deleted = db.cur.rowcount
        total_deleted += deleted
        db.conn.commit()

        pct = total_deleted * 100 // total if total else 0
        log(
            f"    Batch {batch_num}/{total_batches}: "
            f"deleted {total_deleted:,}/{total:,} ({pct}%)",
        )

        if deleted < batch_size:
            break

    return total_deleted


def _cleanup_orphans(
    db: _DbCtx,
    orphan: _TableRef,
    ref: _TableRef,
) -> int:
    """Clean orphaned rows using LEFT JOIN pattern with batch delete.

    Replaces the slow NOT IN subquery with LEFT JOIN ... IS NULL.
    Returns total deleted count.
    """
    created_index = False
    with contextlib.suppress(sqlite3.Error):
        created_index = _ensure_index(db.cur, db.conn, ref.table, ref.column)

    try:
        # Count orphans first
        log("    Counting orphans...")
        db.cur.execute(
            f"SELECT COUNT(*) FROM {orphan.table} ot "
            f"LEFT JOIN {ref.table} rt ON ot.{orphan.column} = rt.{ref.column} "
            f"WHERE rt.{ref.column} IS NULL",
        )
        orphan_count: int = db.cur.fetchone()[0]

        if orphan_count == 0:
            log("    No orphan rows found")
            return 0

        log(f"    Found {orphan_count:,} orphan rows")
        batch_size = _get_batch_size(orphan_count)
        total_deleted = 0
        batch_num = 0
        total_batches = (orphan_count + batch_size - 1) // batch_size

        while True:
            batch_num += 1
            db.cur.execute(
                f"DELETE FROM {orphan.table} WHERE {orphan.column} IN ("
                f"  SELECT ot.{orphan.column} FROM {orphan.table} ot"
                f"  LEFT JOIN {ref.table} rt"
                f"    ON ot.{orphan.column} = rt.{ref.column}"
                f"  WHERE rt.{ref.column} IS NULL"
                f"  LIMIT ?"
                ")",
                (batch_size,),
            )
            deleted = db.cur.rowcount
            total_deleted += deleted
            db.conn.commit()

            if deleted < batch_size:
                break

            pct = total_deleted * 100 // orphan_count if orphan_count else 0
            log(
                f"    Batch {batch_num}/{total_batches}: "
                f"deleted {total_deleted:,}/{orphan_count:,} ({pct}%)",
            )

        return total_deleted

    finally:
        if created_index:
            _drop_temp_index(db.cur, db.conn, ref.table, ref.column)


def _check_vacuum_feasibility() -> tuple[bool, float, float]:
    """Check if VACUUM is feasible based on available disk space.

    Returns (feasible, db_size_mb, free_space_mb).
    """
    db_size_mb = get_db_size()
    if db_size_mb == 0:
        return (False, 0.0, 0.0)

    stat = os.statvfs(DB_PATH)
    free_space_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)

    # VACUUM needs approximately 1x DB size of free space + safety margin
    needed_mb = db_size_mb * VACUUM_SPACE_SAFETY_MARGIN
    feasible = free_space_mb >= needed_mb

    return (feasible, db_size_mb, free_space_mb)


def _maybe_vacuum(dry_run: bool = False) -> None:
    """Run VACUUM if feasible, with disk space check and progress logging."""
    feasible, db_size_mb, free_space_mb = _check_vacuum_feasibility()

    if not feasible:
        if db_size_mb > 0:
            log(
                f"⚠️  Skipping VACUUM — not enough disk space "
                f"(DB: {db_size_mb:.1f} MB, free: {free_space_mb:.1f} MB, "
                f"need: {db_size_mb * VACUUM_SPACE_SAFETY_MARGIN:.1f} MB)",
            )
        return

    if dry_run:
        eta = db_size_mb / VACUUM_SPEED_ESTIMATE_MB_PER_SEC
        log(
            f"Would VACUUM (DB: {db_size_mb:.1f} MB, "
            f"free: {free_space_mb:.1f} MB, est. {eta:.0f}s)",
        )
        return

    t = _log_phase_start("VACUUM")
    log(f"    DB size before: {db_size_mb:.1f} MB")

    vacuum_conn = sqlite3.connect(DB_PATH, isolation_level=None)
    try:
        vacuum_conn.execute("VACUUM")
    finally:
        vacuum_conn.close()

    after_mb = get_db_size()
    saved = db_size_mb - after_mb
    _log_phase_end(
        "VACUUM",
        t,
        f"DB: {db_size_mb:.1f} → {after_mb:.1f} MB ({saved:.1f} MB saved)",
    )


def purge_database(dry_run: bool = False) -> tuple[int, int]:
    """Purge old database records and vacuum.

    Phases:
      1. Count purgeable states/events
      2. Batch delete states
      3. Batch delete events
      4. Clean orphaned state_attributes (LEFT JOIN)
      5. Clean orphaned event_data (LEFT JOIN)
      6. VACUUM (with disk space check)
    """
    if not DB_PATH.exists():
        log("✓ No database found, skipping")
        return (0, 0)

    purge_days = get_recorder_purge_days()
    log(f"Using purge_keep_days: {purge_days}")

    cutoff_ts = int((datetime.now(tz=None) - timedelta(days=purge_days)).timestamp())  # noqa: DTZ005 — local time intentional

    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            originals = _configure_pragmas(conn)
            try:
                cur = conn.cursor()

                # Phase 1: Count
                t = _log_phase_start("Count")
                states, events = _count_purgeable(cur, cutoff_ts)
                _log_phase_end(
                    "Count", t, f"{states:,} states, {events:,} events",
                )

                if not (states or events):
                    log("✓ No old records to purge")
                    return (0, 0)

                if dry_run:
                    log(
                        f"Would purge {states:,} states, {events:,} events"
                        f" older than {purge_days} days",
                    )
                    _maybe_vacuum(dry_run=True)
                    return (states, events)

                log(
                    f"Purging {states:,} states, {events:,} events"
                    f" older than {purge_days} days",
                )

                db = _DbCtx(cur=cur, conn=conn)

                # Phase 2: Delete states
                if states:
                    t = _log_phase_start("States")
                    batch_size = _get_batch_size(states)
                    deleted = _batch_delete_table(
                        db,
                        _TableRef("states", "last_updated_ts"),
                        cutoff_ts, states, batch_size,
                    )
                    _log_phase_end("States", t, f"deleted {deleted:,} rows")

                # Phase 3: Delete events
                if events:
                    t = _log_phase_start("Events")
                    batch_size = _get_batch_size(events)
                    deleted = _batch_delete_table(
                        db,
                        _TableRef("events", "time_fired_ts"),
                        cutoff_ts, events, batch_size,
                    )
                    _log_phase_end("Events", t, f"deleted {deleted:,} rows")

                # Phase 4: Orphan attributes
                t = _log_phase_start("Orphan Attributes")
                orphan_attrs = _cleanup_orphans(
                    db,
                    _TableRef("state_attributes", "attributes_id"),
                    _TableRef("states", "attributes_id"),
                )
                _log_phase_end(
                    "Orphan Attributes", t,
                    f"deleted {orphan_attrs:,} rows",
                )

                # Phase 5: Orphan event data
                t = _log_phase_start("Orphan Event Data")
                orphan_events = _cleanup_orphans(
                    db,
                    _TableRef("event_data", "data_id"),
                    _TableRef("events", "data_id"),
                )
                _log_phase_end(
                    "Orphan Event Data", t,
                    f"deleted {orphan_events:,} rows",
                )

            finally:
                _restore_pragmas(conn, originals)

        # Phase 6: VACUUM (outside transaction)
        _maybe_vacuum()

    except sqlite3.Error as e:
        log(f"⚠️  Database error: {e}")
        return (0, 0)
    else:
        log("✓ Database purged")
        return (states, events)


def cleanup_old_backups(dry_run: bool = False) -> int:
    """Remove backup files older than BACKUP_RETENTION_DAYS."""
    cutoff = (datetime.now(tz=None) - timedelta(days=BACKUP_RETENTION_DAYS)).timestamp()  # noqa: DTZ005 — local time intentional

    total_backups = len(list(STORAGE_PATH.glob("*.backup.*")))

    files_to_remove = []
    for f in STORAGE_PATH.glob("*.backup.*"):
        try:
            if f.stat().st_mtime < cutoff:
                files_to_remove.append(f)
        except OSError:
            pass

    if dry_run:
        if files_to_remove:
            log(f"Would remove {len(files_to_remove)} old backup files")
        return len(files_to_remove)

    removed = 0
    for f in files_to_remove:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass

    if removed:
        log(
            f"✓ Removed {removed} old backup files"
            f" (older than {BACKUP_RETENTION_DAYS} days)",
        )
    elif total_backups > 0:
        log(
            f"✓ No old backup files to remove"
            f" (found {total_backups} backups,"
            f" all within {BACKUP_RETENTION_DAYS} days)",
        )
    else:
        log("✓ No backup files found")

    return removed


# ============================================================
# Restore Functions
# ============================================================

def scan_backup_files() -> list[BackupInfo]:
    """Scan .storage/ folder for backup files.

    Returns list of BackupInfo sorted by timestamp (newest first).
    """
    backups = []

    for backup_path in STORAGE_PATH.glob("*.backup.*"):
        try:
            # Get file stats once (optimization: avoid multiple stat() calls)
            file_stat = backup_path.stat()

            # Parse timestamp from filename using pre-compiled pattern
            match = BACKUP_PATTERN.search(backup_path.name)
            if not match:
                # Fallback to file mtime if timestamp not in filename
                timestamp = datetime.fromtimestamp(file_stat.st_mtime, tz=None)  # noqa: DTZ006 — local time intentional
            else:
                timestamp_str = match.group(1)
                timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")  # noqa: DTZ007 — local time intentional

            # Determine file type
            if "entity_registry" in backup_path.name:
                file_type = "entity_registry"
            elif "device_registry" in backup_path.name:
                file_type = "device_registry"
            else:
                file_type = "unknown"

            # Load JSON and count records (entities or devices depending on type)
            try:
                data = load_json(backup_path, use_cache=False)  # Don't cache backups
                record_key = "devices" if file_type == "device_registry" else "entities"
                entity_count = len(data.get("data", {}).get(record_key, []))
            except (ValueError, KeyError):
                # Corrupted file, skip
                log(f"⚠️  Skipping corrupted backup: {backup_path.name}")
                continue

            # Calculate file size (use cached stat)
            size_mb = file_stat.st_size / (1024 * 1024)

            backups.append(BackupInfo(
                path=backup_path,
                timestamp=timestamp,
                file_type=file_type,
                size_mb=size_mb,
                entity_count=entity_count,
            ))

        except (OSError, ValueError) as e:
            log(f"⚠️  Error reading backup {backup_path.name}: {e}")
            continue

    # Sort by timestamp (newest first)
    backups.sort(key=lambda b: b.timestamp, reverse=True)

    return backups


_DIFF_ATTRS = (
    "platform", "device_id", "config_entry_id", "original_name", "disabled_by",
)


def compare_registries(
    backup_data: dict[str, Any],
    current_data: dict[str, Any],
) -> EntityDiff:
    """Compare backup and current registry to find differences.

    Returns EntityDiff with deleted, new, and modified entities.
    """
    # Build entity_id -> entity dict for both registries
    backup_entities = {
        e["entity_id"]: e
        for e in backup_data.get("data", {}).get("entities", [])
    }
    current_entities = {
        e["entity_id"]: e
        for e in current_data.get("data", {}).get("entities", [])
    }

    backup_ids = set(backup_entities.keys())
    current_ids = set(current_entities.keys())

    # Find deleted entities (in backup but not in current)
    deleted = [backup_entities[eid] for eid in (backup_ids - current_ids)]

    # Find new entities (in current but not in backup)
    new = [current_entities[eid] for eid in (current_ids - backup_ids)]

    modified = []
    common_ids = backup_ids & current_ids

    for eid in common_ids:
        backup_entity = backup_entities[eid]
        current_entity = current_entities[eid]

        if any(
            backup_entity.get(attr) != current_entity.get(attr)
            for attr in _DIFF_ATTRS
        ):
            modified.append((backup_entity, current_entity))

    return EntityDiff(deleted=deleted, new=new, modified=modified)


def _print_diff_section_header(title: str, count: int) -> None:
    print("=" * 60)
    print(f"{title}: {count}")
    print("=" * 60)


def _print_deleted_entities(deleted: list[dict[str, Any]]) -> None:
    _print_diff_section_header("DELETED ENTITIES (in backup but not in current)", len(deleted))
    if not deleted:
        print("  None")
        print()
        return
    for i, entity in enumerate(deleted, 1):
        entity_id = entity.get("entity_id", "unknown")
        platform = entity.get("platform", "unknown")
        name = entity.get("original_name", "")
        print(f"  {i:2d}. {entity_id} ({platform})")
        if name:
            print(f"      Name: {name}")
    print()


def _print_new_entities(new_entities: list[dict[str, Any]]) -> None:
    _print_diff_section_header("NEW ENTITIES (in current but not in backup)", len(new_entities))
    if not new_entities:
        print("  None")
        print()
        return
    for i, entity in enumerate(new_entities, 1):
        entity_id = entity.get("entity_id", "unknown")
        platform = entity.get("platform", "unknown")
        print(f"  {i:2d}. {entity_id} ({platform})")
    print()


def _print_modified_entities(
    modified: list[tuple[dict[str, Any], dict[str, Any]]],
) -> None:
    _print_diff_section_header("MODIFIED ENTITIES", len(modified))
    if not modified:
        print("  None")
        print()
        return
    for i, (backup_entity, current_entity) in enumerate(modified, 1):
        entity_id = backup_entity.get("entity_id", "unknown")
        print(f"  {i:2d}. {entity_id}")
        for attr in _DIFF_ATTRS:
            backup_val = backup_entity.get(attr)
            current_val = current_entity.get(attr)
            if backup_val != current_val:
                print(f"      {attr}: {backup_val} → {current_val}")
    print()


def preview_backup_diff(backup_info: BackupInfo) -> None:
    """Display differences between backup and current registry."""
    try:
        backup_data = load_json(backup_info.path, use_cache=False)
        current_data = load_json(ENTITY_REGISTRY)
    except (FileNotFoundError, ValueError) as e:
        log(f"⚠️  Error loading registries: {e}")
        return

    diff = compare_registries(backup_data, current_data)

    print(f"\nBackup: {backup_info.path.name}")
    print(f"Timestamp: {backup_info.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Entities in backup: {backup_info.entity_count}")
    print()

    _print_deleted_entities(diff.deleted)
    _print_new_entities(diff.new)
    _print_modified_entities(diff.modified)


def _prompt_restore_selection(
    deleted: list[dict[str, Any]],
) -> list[dict[str, Any]] | None:
    """Prompt user to pick which deleted entities to restore.

    Returns list of selected entity dicts, or None if aborted/empty.
    """
    print(f"\nFound {len(deleted)} deleted entities:")
    print("=" * 60)
    for i, entity in enumerate(deleted, 1):
        entity_id = entity.get("entity_id", "unknown")
        platform = entity.get("platform", "unknown")
        name = entity.get("original_name", "")
        print(f"  [{i:2d}] {entity_id} ({platform})")
        if name:
            print(f"       Name: {name}")
    print()
    print("Enter selection:")
    print("  - Numbers: 1,3,5 or 1-5 or 1,3-5,8")
    print("  - 'all' to restore all")
    print("  - 'none' or Enter to skip")
    print()

    try:
        selection = input("Selection: ")
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return None

    indices = parse_selection(selection, len(deleted))
    if not indices:
        log("No entities selected, skipping")
        return None

    return [deleted[i - 1] for i in sorted(indices)]


def _apply_restore(selected_entities: list[dict[str, Any]]) -> int:
    """Perform the actual restore with HA stopped. Returns count restored."""
    log("Stopping Home Assistant...")
    try:
        with ha_stopped():
            backup_file(ENTITY_REGISTRY)

            # Re-read registry AFTER HA has stopped — the copy loaded before
            # the user interaction may be stale (HA could have written to it
            # while the user was reading the preview).
            fresh_data = load_json(ENTITY_REGISTRY, use_cache=False)

            current_entity_ids = {
                e["entity_id"] for e in fresh_data["data"]["entities"]
            }
            restored_count = 0

            for entity in selected_entities:
                entity_id = entity.get("entity_id")
                if entity_id in current_entity_ids:
                    log(f"⚠️  Skipping {entity_id} (already exists)")
                    continue

                fresh_data["data"]["entities"].append(entity)
                restored_count += 1

            save_json(ENTITY_REGISTRY, fresh_data)
            log(f"✓ Restored {restored_count} entities")
            return restored_count
    except (RuntimeError, FileNotFoundError, ValueError) as e:
        log(f"⚠️  Restore failed: {e}")
        return 0


def selective_restore_entities(backup_info: BackupInfo, dry_run: bool = False) -> int:
    """Restore selected entities from backup.

    Returns count of restored entities.
    """
    try:
        backup_data = load_json(backup_info.path, use_cache=False)
        current_data = load_json(ENTITY_REGISTRY)
    except (FileNotFoundError, ValueError) as e:
        log(f"⚠️  Error loading registries: {e}")
        return 0

    diff = compare_registries(backup_data, current_data)
    if not diff.deleted:
        log("✓ No deleted entities to restore")
        return 0

    selected_entities = _prompt_restore_selection(diff.deleted)
    if not selected_entities:
        return 0

    print(f"\nWill restore {len(selected_entities)} entities:")
    for entity in selected_entities:
        entity_id = entity.get("entity_id", "unknown")
        platform = entity.get("platform", "unknown")
        print(f"  - {entity_id} ({platform})")
    print()

    if dry_run:
        log(f"DRY RUN: Would restore {len(selected_entities)} entities")
        return len(selected_entities)

    if not confirm_action(f"Restore these {len(selected_entities)} entities?"):
        print("Aborted.")
        return 0

    return _apply_restore(selected_entities)


def full_restore_registry(backup_info: BackupInfo, dry_run: bool = False) -> int:
    """Fully restore registry from backup.

    Returns entity count from backup.
    """
    # Load and validate backup file
    try:
        backup_data = load_json(backup_info.path, use_cache=False)
    except (FileNotFoundError, ValueError) as e:
        log(f"⚠️  Error loading backup: {e}")
        return 0

    # Check data.entities exists
    if "data" not in backup_data or "entities" not in backup_data["data"]:
        log("⚠️  Invalid backup format: missing data.entities")
        return 0

    backup_entity_count = len(backup_data["data"]["entities"])

    # Load current registry and count entities
    try:
        current_data = load_json(ENTITY_REGISTRY)
        current_entity_count = len(current_data["data"]["entities"])
    except (FileNotFoundError, ValueError):
        current_entity_count = 0

    # Display entity count difference
    print(f"\nBackup: {backup_info.path.name}")
    print(f"Timestamp: {backup_info.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Entities in backup: {backup_entity_count}")
    print(f"Entities in current: {current_entity_count}")
    print(f"Difference: {backup_entity_count - current_entity_count:+d}")
    print()

    # Warn if difference > threshold
    if current_entity_count > 0:
        diff_percent = (
            abs(backup_entity_count - current_entity_count)
            / current_entity_count * 100
        )
        if diff_percent > ENTITY_COUNT_DIFF_WARNING_THRESHOLD:
            print(f"⚠️  WARNING: Entity count differs by {diff_percent:.1f}%!")
            print("   This is a significant change. Review carefully.")
            print()

    if dry_run:
        log(f"DRY RUN: Would restore {backup_entity_count} entities")
        return backup_entity_count

    # Confirm action
    if not confirm_action("Fully restore registry from this backup?"):
        print("Aborted.")
        return 0

    # Stop HA
    log("Stopping Home Assistant...")
    try:
        with ha_stopped():
            # Backup current registry
            backup_file(ENTITY_REGISTRY)

            # Copy backup file to registry path
            shutil.copy2(backup_info.path, ENTITY_REGISTRY)
            invalidate_cache(ENTITY_REGISTRY)
            log(f"✓ Restored {backup_entity_count} entities from backup")

            return backup_entity_count
    except RuntimeError:
        return 0


def _print_backup_list(backups: list[BackupInfo]) -> None:
    """Print numbered list of backup files."""
    print("\nAvailable backups:")
    for i, backup in enumerate(backups, 1):
        ts = backup.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"  [{i}] {ts} - {backup.file_type}"
            f" ({backup.entity_count} entities)",
        )
    print()


def _select_backup(backups: list[BackupInfo]) -> BackupInfo | None:
    """Prompt user to select a backup from list.

    Returns selected BackupInfo or None if cancelled/invalid.
    """
    _print_backup_list(backups)
    try:
        selection = input("Select backup number (or Enter to cancel): ").strip()
        if not selection:
            return None
        idx = int(selection) - 1
        if 0 <= idx < len(backups):
            return backups[idx]
    except (ValueError, EOFError, KeyboardInterrupt):
        pass
    print("Invalid selection")
    return None


def _print_restore_menu() -> None:
    print("\n" + "=" * 70)
    print("  Restore from Backup")
    print("=" * 70)
    print()
    print("  1. List available backups")
    print("  2. Preview backup differences")
    print("  3. Selective restore entities")
    print("  4. Full restore registry")
    print()
    print("  r. Refresh backup list")
    print("  b. Back to main menu")
    print()


def _list_backups_detailed(backups: list[BackupInfo]) -> None:
    print(f"\nFound {len(backups)} backup files:")
    print("=" * 60)
    print(
        f"{'#':<4} {'Timestamp':<20} {'Type':<18}"
        f" {'Entities':<10} {'Size (MB)':<10}",
    )
    print("-" * 60)
    for i, backup in enumerate(backups, 1):
        timestamp_str = backup.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        print(
            f"{i:<4} {timestamp_str:<20}"
            f" {backup.file_type:<18}"
            f" {backup.entity_count:<10}"
            f" {backup.size_mb:<10.2f}",
        )
    print()


def restore_menu() -> None:
    """Interactive restore menu."""
    cached_backups: list[BackupInfo] | None = None

    while True:
        _print_restore_menu()

        try:
            choice = input("  Select option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to main menu...")
            break

        if choice == "b":
            break

        if choice == "r":
            cached_backups = None
            log("✓ Backup list refreshed")
            continue

        if choice not in {"1", "2", "3", "4"}:
            print("Invalid option, try again.")
            continue

        if cached_backups is None:
            cached_backups = scan_backup_files()
        if not cached_backups:
            log("No backup files found")
            continue

        if choice == "1":
            _list_backups_detailed(cached_backups)
            continue

        selected = _select_backup(cached_backups)
        if not selected:
            continue

        if choice == "2":
            preview_backup_diff(selected)
        elif choice == "3":
            selective_restore_entities(selected)
            cached_backups = None
            invalidate_cache()
        elif choice == "4":
            full_restore_registry(selected)
            cached_backups = None
            invalidate_cache()


def find_suffix_entities() -> list[tuple[str, str, str]]:
    """Find entities with numeric suffix (_2, _3, etc.) that might be duplicates.

    Returns list of tuples: (old_id, new_id, platform)

    Note: This returns ALL entities ending with _N where N >= 2.
    User must manually select which ones to fix, as some are legitimate
    (e.g., button_4, sim_2, pm2_5).
    """
    if not ENTITY_REGISTRY.exists():
        return []

    try:
        data = load_json(ENTITY_REGISTRY)
    except (FileNotFoundError, ValueError):
        return []

    entities = data.get("data", {}).get("entities", [])

    # Build set of all entity IDs for quick lookup
    all_entity_ids = {e.get("entity_id", "") for e in entities}

    # Use pre-compiled pattern
    candidates = []
    for entity in entities:
        entity_id = entity.get("entity_id", "")
        platform = entity.get("platform", "")

        # Check if entity_id ends with numeric suffix (_2, _3, etc.)
        match = DUPLICATE_SUFFIX_PATTERN.search(entity_id)
        if not match:
            continue

        # Calculate base entity ID (without suffix)
        suffix = match.group(0)  # e.g., "_2"
        new_id = entity_id[:-len(suffix)]

        # Only include if base entity does NOT exist
        if new_id in all_entity_ids:
            continue

        candidates.append((entity_id, new_id, platform))

    # Exclude candidates where multiple suffixed entities map to the same base.
    # Renaming both would create duplicate entity_ids — registry corruption.
    target_counts: dict[str, int] = {}
    for _old, new_id, _platform in candidates:
        target_counts[new_id] = target_counts.get(new_id, 0) + 1

    return [c for c in candidates if target_counts[c[1]] == 1]


def _parse_range(part: str, max_num: int) -> set[int] | None:
    """Parse a `start-end` range. Returns None if invalid or empty."""
    try:
        raw_start, raw_end = (int(p) for p in part.split("-", 1))
    except ValueError:
        return None
    start = max(1, raw_start)
    end = min(max_num, raw_end)
    return set(range(start, end + 1)) if start <= end else None


def _parse_single(part: str, max_num: int) -> int | None:
    """Parse a single number. Returns None if invalid or out of range."""
    try:
        num = int(part)
    except ValueError:
        return None
    return num if 1 <= num <= max_num else None


def parse_selection(selection: str, max_num: int) -> set[int]:
    """Parse user selection string into set of indices.

    Supports:
    - Single numbers: "1", "5"
    - Comma-separated: "1,3,5"
    - Ranges: "1-5"
    - Mixed: "1,3-5,8"
    - Special: "all", "none", ""
    """
    selection = selection.strip().lower()

    if selection in ("", "none", "n", "q"):
        return set()

    if selection == "all":
        return set(range(1, max_num + 1))

    indices: set[int] = set()
    skipped: list[str] = []

    for part in (p for p in selection.replace(" ", "").split(",") if p):
        if "-" in part:
            got = _parse_range(part, max_num)
            if got is None:
                skipped.append(part)
            else:
                indices.update(got)
        else:
            got_num = _parse_single(part, max_num)
            if got_num is None:
                skipped.append(part)
            else:
                indices.add(got_num)

    if skipped:
        log(f"⚠️  Ignored invalid selection parts: {', '.join(skipped)}")

    return indices


def fix_entity_suffix(dry_run: bool = False) -> int:
    """Fix numeric suffix in entity registry with interactive selection."""
    candidates = find_suffix_entities()

    if not candidates:
        log("✓ No numeric suffix entities found")
        return 0

    # In dry-run mode, just list all candidates
    if dry_run:
        log(f"Found {len(candidates)} entities with numeric suffix:")
        for old_id, new_id, platform in candidates:
            log(f"  - {old_id} -> {new_id} ({platform})")
        return len(candidates)

    # Interactive mode: let user select which to fix
    print(f"\nFound {len(candidates)} entities with numeric suffix:")
    print("=" * 60)
    print("⚠️  WARNING: Not all suffixes are duplicates!")
    print("   Some are legitimate (e.g., button_4, sim_2, pm2_5)")
    print("   Review carefully before selecting.")
    print("=" * 60)
    print()

    for i, (old_id, new_id, platform) in enumerate(candidates, 1):
        print(f"  [{i:2d}] {old_id}")
        print(f"       -> {new_id} ({platform})")

    print()
    print("Enter selection:")
    print("  - Numbers: 1,3,5 or 1-5 or 1,3-5,8")
    print("  - 'all' to fix all (DANGEROUS!)")
    print("  - 'none' or Enter to skip")
    print()

    try:
        selection = input("Selection: ")
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return 0

    indices = parse_selection(selection, len(candidates))

    if not indices:
        log("No entities selected, skipping")
        return 0

    # Get selected fixes
    selected_fixes = [candidates[i - 1] for i in sorted(indices)]

    print(f"\nWill fix {len(selected_fixes)} entities:")
    for old_id, new_id, _platform in selected_fixes:
        print(f"  - {old_id} -> {new_id}")

    if not confirm_action(f"Fix these {len(selected_fixes)} entities?"):
        print("Aborted.")
        return 0

    # Backup before modification
    backup_file(ENTITY_REGISTRY)

    data = load_json(ENTITY_REGISTRY)
    fix_map = {old: new for old, new, _ in selected_fixes}

    for entity in data["data"]["entities"]:
        entity_id = entity.get("entity_id")
        if entity_id in fix_map:
            entity["entity_id"] = fix_map[entity_id]

    save_json(ENTITY_REGISTRY, data)
    log(f"✓ Fixed {len(selected_fixes)} entity suffixes")
    return len(selected_fixes)


# ============================================================
# Menu System
# ============================================================

def print_menu() -> None:
    """Print interactive menu."""
    print("\n" + "=" * 70)
    print(f"  Home Assistant Cleanup Tool  v{VERSION}")
    print("=" * 70)
    print(f"  Config: {CONFIG_PATH}")
    db_size = get_db_size()
    if db_size:
        print(f"  Database: {db_size:.1f} MB")
    print("-" * 70)
    print("  ⚠️  This tool modifies HA registries and database.")
    print("     Always back up first.")
    print("  💡 DB purge on large DBs may take several minutes —")
    print("     progress will be shown.")
    print("=" * 70)
    print()
    print("  1. Full cleanup (options 2-4, 6 — optimized)")
    print("  2. Remove orphaned entities (missing device/config/definition)")
    print("  3. Clean deleted registry items (deleted_entities/devices)")
    print("  4. Purge old database records (optimized batch + progress)")
    print("  5. Fix numeric suffix (_2, _3, etc.) - interactive")
    print(f"  6. Clean old backup files (>{BACKUP_RETENTION_DAYS} days)")
    print("  7. Restore from backup (selective or full)")
    print()
    print("  d. Dry run (preview all)")
    print("  q. Quit")
    print()


def confirm_action(msg: str) -> bool:
    """Ask user for confirmation."""
    try:
        response = input(f"⚠️  {msg} [y/N]: ")
        return response.lower() == "y"
    except (EOFError, KeyboardInterrupt):
        return False


def run_with_ha_restart(
    operations: list[Callable[..., object]],
    dry_run: bool = False,
) -> None:
    """Run operations that require HA restart."""
    if dry_run:
        for op in operations:
            op(dry_run=True)
        return

    if not confirm_action("This will stop Home Assistant. Continue?"):
        print("Aborted.")
        return

    db_before = get_db_size()

    log("Stopping Home Assistant...")
    try:
        with ha_stopped():
            for op in operations:
                try:
                    op(dry_run=False)
                except (OSError, ValueError, sqlite3.Error) as e:
                    log(f"⚠️  Error in {op.__name__}: {e}")

            cleanup_old_backups()

            db_after = get_db_size()
            if db_before and db_after:
                saved = db_before - db_after
                if saved > 0:
                    log(
                        f"Database: {db_before:.1f} MB → "
                        f"{db_after:.1f} MB ({saved:.1f} MB saved)",
                    )
    except RuntimeError:
        return

    log("Done!")


def _run_dry_run_preview() -> None:
    print("\n" + "=" * 70)
    log("DRY RUN - Preview all changes")
    print("=" * 70 + "\n")
    cleanup_orphaned_entities(dry_run=True)
    cleanup_deleted_items(dry_run=True)
    purge_database(dry_run=True)
    fix_entity_suffix(dry_run=True)
    cleanup_old_backups(dry_run=True)


def _run_suffix_fix() -> None:
    """Interactive suffix fix with its own HA stop/start cycle."""
    candidates = find_suffix_entities()
    if not candidates:
        log("✓ No numeric suffix entities found")
        return

    if not confirm_action("This will stop Home Assistant. Continue?"):
        print("Aborted.")
        return

    log("Stopping Home Assistant...")
    try:
        with ha_stopped():
            fix_entity_suffix(dry_run=False)
    except RuntimeError:
        return
    log("Done!")


def interactive_menu() -> None:
    """Run interactive menu loop."""
    while True:
        print_menu()
        try:
            choice = input("  Select option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if choice == "q":
            print("Bye!")
            break
        if choice == "d":
            _run_dry_run_preview()
        elif choice == "1":
            run_with_ha_restart([
                cleanup_orphaned_entities,
                cleanup_deleted_items,
                purge_database,
            ])
            print("\n⚠️  Suffix fix requires manual selection. Run option 5 separately.")
        elif choice == "2":
            run_with_ha_restart([cleanup_orphaned_entities])
        elif choice == "3":
            run_with_ha_restart([cleanup_deleted_items])
        elif choice == "4":
            run_with_ha_restart([purge_database])
        elif choice == "5":
            _run_suffix_fix()
        elif choice == "6":
            cleanup_old_backups()
        elif choice == "7":
            restore_menu()
        else:
            print("Invalid option, try again.")


# ============================================================
# Main Entry Point
# ============================================================

def main() -> None:
    """Run the main entry point."""
    if "--dry-run" in sys.argv:
        log("=" * 50)
        log("Home Assistant Cleanup (DRY RUN)")
        log("=" * 50)
        log(f"Config path: {CONFIG_PATH}")
        db_size = get_db_size()
        if db_size:
            log(f"Database size: {db_size:.1f} MB\n")

        orphans = cleanup_orphaned_entities(dry_run=True)
        deleted = cleanup_deleted_items(dry_run=True)
        purge_database(dry_run=True)
        suffix = fix_entity_suffix(dry_run=True)
        old_backups = cleanup_old_backups(dry_run=True)

        log("\n" + "=" * 50)
        log("Summary:")
        log(f"  Orphaned entities: {orphans}")
        log(f"  Deleted registry items: {deleted}")
        log(f"  Suffix fixes: {suffix}")
        log(f"  Old backup files: {old_backups}")
        log("=" * 50)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
