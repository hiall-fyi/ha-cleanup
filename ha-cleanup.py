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

VERSION = "1.7.1"

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
HA_STOP_WAIT_SECONDS = 2           # Initial grace before probing
HA_STOP_MAX_WAIT_SECONDS = 30      # Give up probing after this
HA_STOP_PROBE_INTERVAL = 1.0

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
YAML_ID_PATTERN = re.compile(r'(?:^|\n)\s*-?\s*id:\s*["\']?([^"\'\n\r]+)["\']?')
# Anchored to column zero so options nested under an entry never match.
YAML_TOP_LEVEL_KEY_PATTERN = re.compile(r"^([A-Za-z0-9_-]+):[ \t]*(?:#.*)?$", re.MULTILINE)
BACKUP_PATTERN = re.compile(r"\.backup\.(\d{8}_\d{6})(?:_\d+)?$")
# Home Assistant's de-duplication counts up from 2 and never emits `_1`, so
# `_2`-`_99` covers real collisions without matching model numbers.
DUPLICATE_SUFFIX_PATTERN = re.compile(r"_([2-9]|[1-9]\d)$")
MAC_TAIL_SEGMENT_PATTERN = re.compile(r"^[0-9a-f]{2}$", re.IGNORECASE)
PORT_SUFFIX_BASE_PATTERN = re.compile(r"_(?:tcp|udp)$", re.IGNORECASE)


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
# Utility Functions
# ============================================================

def _records(data: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Read a list from `data["data"][<key>]`, or `[]` if missing or malformed.

    Always returns a list, so callers can `len()` or iterate without guarding.
    Read-only: mutation sites index explicitly instead.
    """
    if not isinstance(data, dict):
        return []
    payload = data.get("data")
    if not isinstance(payload, dict):
        return []
    records = payload.get(key)
    if not isinstance(records, list):
        return []
    return records


def _has_record_list(data: dict[str, Any], key: str) -> bool:
    """Check that `data["data"][<key>]` really is a list.

    Restore paths need to tell an empty registry from a truncated one, which
    `_records` deliberately flattens together.
    """
    if not isinstance(data, dict):
        return False
    payload = data.get("data")
    return isinstance(payload, dict) and isinstance(payload.get(key), list)


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


def load_json(path: Path) -> dict[str, Any]:
    """Load JSON file with error handling.

    Reads from disk every call. Callers mutate what they get, so they must not
    share an object: do not add a cache here.
    """
    if not path.exists():
        msg = f"File not found: {path}"
        raise FileNotFoundError(msg)

    try:
        with path.open(encoding="utf-8") as f:
            data: dict[str, Any] = json.load(f)
            return data
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON in {path}: {e}"
        raise ValueError(msg) from e


def save_json(path: Path, data: dict[str, Any]) -> None:
    """Save data to JSON file via temp-file + atomic rename.

    Writes to a `.tmp.<pid>` sibling, fsyncs, then renames over the target.
    POSIX guarantees the rename is atomic from a reader's perspective: any
    concurrent reader sees either the old inode or the new one, never a
    partial write.

    Callers are expected to coordinate with Home Assistant separately
    (see `ha_stopped`). This function does not hold a lock on the target —
    the atomic rename is sufficient because HA is not running when this
    runs.
    """
    temp_path = Path(f"{path}.tmp.{os.getpid()}")

    try:
        with temp_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())  # Force write to disk before rename

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

    except Exception as e:
        # Clean up temp file on error
        if temp_path.exists():
            temp_path.unlink()
        msg = f"Failed to save JSON to {path}: {e}"
        raise ValueError(msg) from e


def get_db_size() -> float:
    """Get total database size in MB, counting the `-wal` and `-shm` sidecars.

    In WAL mode freed pages sit in `-wal` until a checkpoint, so the main file
    alone understates what is on disk.
    """
    total = 0
    for suffix in ("", "-wal", "-shm"):
        sidecar = Path(f"{DB_PATH}{suffix}")
        try:
            total += sidecar.stat().st_size
        except OSError:
            continue  # absent (not in WAL mode / never created) or unreadable
    return total / (1024 * 1024)


def _run_ha_command(cmd: list[str]) -> bool:
    """Run an HA lifecycle command. Returns True on success.

    The cmd list is always a hardcoded literal from stop_ha/start_ha —
    no user input ever reaches subprocess.
    """
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)  # noqa: S603 — cmd is hardcoded
    except subprocess.CalledProcessError as e:
        stderr = (e.stderr or b"").decode(errors="replace").strip()
        if stderr:
            logger.debug("Command %s failed: %s", cmd, stderr)
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired):
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


def _wait_for_db_unlocked() -> None:
    """Poll the HA database until SQLite can open it without `database is locked`.

    Starts with a short grace period, then probes at HA_STOP_PROBE_INTERVAL
    until HA_STOP_MAX_WAIT_SECONDS. If no DB exists (fresh install), returns
    immediately after the grace period.
    """
    time.sleep(HA_STOP_WAIT_SECONDS)

    if not DB_PATH.exists():
        return

    deadline = time.monotonic() + (HA_STOP_MAX_WAIT_SECONDS - HA_STOP_WAIT_SECONDS)
    while True:
        try:
            probe = sqlite3.connect(DB_PATH, timeout=0.1)
            try:
                probe.execute("PRAGMA schema_version").fetchone()
            finally:
                probe.close()
        except sqlite3.OperationalError:
            if time.monotonic() >= deadline:
                logger.info("⚠️  DB still locked — HA may not have finished stopping")
                return
            time.sleep(HA_STOP_PROBE_INTERVAL)
            continue
        return


@contextmanager
def ha_stopped() -> Generator[str | None]:
    """Context manager to stop and restart HA around operations.

    Yields the stop method string (or None if manual stop).
    Ensures HA is restarted in the finally block.
    """
    method = stop_ha()
    if not method:
        logger.info("⚠️  Could not stop HA automatically.")
        if not confirm_action("Please stop HA manually. Continue when stopped?"):
            msg = "HA not stopped — operation aborted"
            raise RuntimeError(msg)

    _wait_for_db_unlocked()
    try:
        yield method
    finally:
        logger.info("Starting Home Assistant...")
        if method:
            if not start_ha(method):
                logger.info("⚠️  Failed to start HA. Please start manually.")
        else:
            logger.info("Please start Home Assistant manually.")


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


def _scan_yaml_for_recorder(path: Path) -> int | None:
    """Read one YAML file and return purge_keep_days if recorder: is present."""
    try:
        return _extract_purge_keep_days(path.read_text(encoding="utf-8"))
    except OSError:
        return None


def _find_purge_days_in_packages() -> int | None:
    """Search packages/*.yaml for a top-level recorder: block."""
    packages_dir = CONFIG_PATH / "packages"
    if not packages_dir.is_dir():
        return None
    for yaml_file in packages_dir.rglob("*.yaml"):
        days = _scan_yaml_for_recorder(yaml_file)
        if days is not None:
            return days
    return None


def get_recorder_purge_days() -> tuple[int, str]:
    """Get purge_keep_days from HA recorder config, fallback to default.

    Returns (days, source) where source is a short human-readable label:
      "configuration.yaml", "packages/<file>", "config_entries", or "default".
    """
    # Try configuration.yaml first
    config_yaml = CONFIG_PATH / "configuration.yaml"
    if config_yaml.exists():
        days = _scan_yaml_for_recorder(config_yaml)
        if days is not None:
            return days, "configuration.yaml"

    # Try packages/*.yaml (HA's packages: !include_dir_named packages/)
    packages_days = _find_purge_days_in_packages()
    if packages_days is not None:
        return packages_days, "packages/*.yaml"

    # Try .storage/core.config_entries for recorder integration
    if CONFIG_ENTRIES.exists():
        try:
            data = load_json(CONFIG_ENTRIES)
            for entry in _records(data, "entries"):
                if entry.get("domain") == "recorder":
                    options = entry.get("options", {})
                    if "purge_keep_days" in options:
                        return int(options["purge_keep_days"]), "config_entries"
        except (FileNotFoundError, ValueError, KeyError):
            pass

    return DEFAULT_PURGE_DAYS, "default"


# ============================================================
# ID Collection Functions
# ============================================================

def extract_ids_from_yaml_file(path: Path) -> set[str]:
    """Extract entity IDs from a YAML file, covering both Home Assistant styles.

    Automations are a list of entries each carrying an `id:` field. Scripts and
    scenes are a mapping whose top-level key is itself the ID.
    """
    ids: set[str] = set()
    if not path.exists():
        return ids

    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return ids

    for match in YAML_ID_PATTERN.finditer(content):
        id_value = match.group(1).strip()
        if id_value and not id_value.startswith("#"):
            ids.add(id_value)

    ids.update(YAML_TOP_LEVEL_KEY_PATTERN.findall(content))
    return ids


def get_entity_ids(
    folder_path: Path,
    yaml_file: str,
    storage_file: str,
) -> set[str]:
    """Collect entity IDs from a folder of YAML files, a root YAML, and UI storage.

    `yaml_file` is the root file (e.g. "automations.yaml"), `storage_file` the
    name under `.storage` (e.g. "automations").
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
            for item in _records(data, "items"):
                if item.get("id"):
                    ids.add(item["id"])
        except (FileNotFoundError, ValueError, KeyError):
            pass

    return ids


def get_automation_ids() -> set[str]:
    """Get all automation IDs from YAML files and UI storage."""
    return get_entity_ids(AUTOMATION_PATH, "automations.yaml", "automations")


def get_script_ids() -> set[str]:
    """Get all script IDs from YAML files and UI storage."""
    return get_entity_ids(SCRIPT_PATH, "scripts.yaml", "scripts")


def get_scene_ids() -> set[str]:
    """Get all scene IDs from YAML files and UI storage."""
    return get_entity_ids(SCENE_PATH, "scenes.yaml", "scenes")


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
            logger.info("⚠️  %s not found, skipping orphan detection", label)
            return []

    try:
        entity_data = load_json(ENTITY_REGISTRY)
        device_data = load_json(DEVICE_REGISTRY)
        config_data = load_json(CONFIG_ENTRIES)
    except (FileNotFoundError, ValueError) as e:
        logger.info("⚠️  Error loading registry files: %s", e)
        return []

    devices = {
        d["id"] for d in _records(device_data, "devices")
    }
    config_entries = {
        e["entry_id"] for e in _records(config_data, "entries")
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
        for entity in _records(entity_data, "entities")
        if _is_entity_orphan(entity, devices, config_entries, definition_ids)
    ]


def cleanup_orphaned_entities(dry_run: bool = False) -> int:
    """Remove orphaned entities from registry."""
    orphans = find_orphaned_entities()

    if not orphans:
        logger.info("✓ No orphaned entities found")
        return 0

    if dry_run:
        logger.info("Found %s orphaned entities:", len(orphans))
        for platform, eid, name in sorted(orphans):
            logger.info("  - %s: %s (%s)", platform, eid, name)
        return len(orphans)

    # Backup before modification
    backup_file(ENTITY_REGISTRY)

    orphan_eids = {o[1] for o in orphans}
    data = load_json(ENTITY_REGISTRY)
    original_count = len(data["data"]["entities"])
    data["data"]["entities"] = [
        e for e in data["data"]["entities"]
        if e.get("entity_id") not in orphan_eids
    ]
    new_count = len(data["data"]["entities"])

    save_json(ENTITY_REGISTRY, data)
    logger.info("✓ Removed %s orphaned entities", original_count - new_count)
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
            logger.info("⚠️  Error loading %s: %s", path, e)
            continue

        deleted_items = _records(data, key)
        n = len(deleted_items)

        if n > 0:
            if dry_run:
                logger.info("Would clean %s %s", n, key.replace('_', ' '))
            else:
                backup_file(path)
                data["data"][key] = []
                save_json(path, data)
                logger.info("✓ Cleaned %s %s", n, key.replace('_', ' '))
            count += n

    if count == 0:
        logger.info("✓ No deleted registry items to clean")

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
    logger.info("  [%s] Starting...", phase)
    return time.monotonic()


def _log_phase_end(phase: str, start_time: float, detail: str = "") -> None:
    """Log phase completion with elapsed time."""
    elapsed = time.monotonic() - start_time
    suffix = f" — {detail}" if detail else ""
    logger.info("  [%s] Done in %ss%s", phase, format(elapsed, ".1f"), suffix)


def _configure_pragmas(conn: sqlite3.Connection) -> dict[str, Any]:
    """Set optimised PRAGMAs for purge operations.

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


def _set_journal_mode_wal(conn: sqlite3.Connection) -> str | None:
    """Switch to WAL for the purge, returning the mode to restore afterwards.

    `journal_mode` persists in the database file, unlike the PRAGMAs above, so
    it has to be put back. Returns None when there is nothing to restore.
    """
    original: str | None = None
    with contextlib.suppress(sqlite3.Error):
        row = conn.execute("PRAGMA journal_mode").fetchone()
        if row and str(row[0]).lower() != "wal":
            original = str(row[0])
    conn.execute("PRAGMA journal_mode=WAL")
    return original


def _checkpoint_and_restore_journal_mode(
    conn: sqlite3.Connection,
    original_mode: str | None,
) -> None:
    """Fold the WAL back into the main DB, then restore journal_mode.

    Runs before VACUUM so the size it reports is the real one. Best-effort: a
    failure here must not fail a purge that already succeeded.
    """
    with contextlib.suppress(sqlite3.Error):
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    if original_mode is None:
        return
    with contextlib.suppress(sqlite3.Error):
        conn.execute(f"PRAGMA journal_mode={original_mode}")


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
    logger.info("    Creating temporary index %s...", idx_name)
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


def _run_batched_delete(
    db: _DbCtx,
    sql: str,
    params: tuple[Any, ...],
    total: int,
    batch_size: int,
) -> int:
    """Run a batched DELETE loop with per-batch progress, commit, and break.

    `sql` is a DELETE statement whose final bound parameter is the batch LIMIT;
    `params` are the parameters that precede that LIMIT (the caller appends the
    LIMIT). Loops until a batch deletes fewer rows than `batch_size`, which
    means the table is drained. Returns total deleted count.
    """
    total_deleted = 0
    batch_num = 0
    total_batches = (total + batch_size - 1) // batch_size  # ceil division

    while True:
        batch_num += 1
        db.cur.execute(sql, (*params, batch_size))
        deleted = db.cur.rowcount
        total_deleted += deleted
        db.conn.commit()

        pct = total_deleted * 100 // total if total else 0
        logger.info(
            "    Batch %d/%d: deleted %s/%s (%d%%)",
            batch_num, total_batches, f"{total_deleted:,}", f"{total:,}", pct,
        )

        if deleted < batch_size:
            break

    return total_deleted


def _unlink_old_state_ids(db: _DbCtx, cutoff_ts: int) -> int:
    """Clear `states.old_state_id` pointers aimed at rows about to be purged.

    The column is a foreign key back into `states`, so deleting without
    unlinking first leaves dangling references. Home Assistant's own recorder
    does the same. Returns the number cleared; a schema without the column is
    not an error.
    """
    try:
        db.cur.execute(
            "UPDATE states SET old_state_id = NULL WHERE old_state_id IN ("
            "  SELECT state_id FROM states WHERE last_updated_ts < ?"
            ")",
            (cutoff_ts,),
        )
    except sqlite3.OperationalError:
        return 0  # no old_state_id / no state_id column on this schema
    unlinked: int = db.cur.rowcount
    db.conn.commit()
    if unlinked > 0:
        logger.info("    Unlinked %s old_state_id references", format(unlinked, ","))
    return unlinked


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
    sql = (
        f"DELETE FROM {target.table} WHERE rowid IN ("
        f"  SELECT rowid FROM {target.table}"
        f"  WHERE {target.column} < ? LIMIT ?"
        ")"
    )
    return _run_batched_delete(db, sql, (cutoff_ts,), total, batch_size)


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
        logger.info("    Counting orphans...")
        db.cur.execute(
            f"SELECT COUNT(*) FROM {orphan.table} ot "
            f"LEFT JOIN {ref.table} rt ON ot.{orphan.column} = rt.{ref.column} "
            f"WHERE rt.{ref.column} IS NULL",
        )
        orphan_count: int = db.cur.fetchone()[0]

        if orphan_count == 0:
            logger.info("    No orphan rows found")
            return 0

        logger.info("    Found %s orphan rows", format(orphan_count, ","))
        batch_size = _get_batch_size(orphan_count)
        sql = (
            f"DELETE FROM {orphan.table} WHERE {orphan.column} IN ("
            f"  SELECT ot.{orphan.column} FROM {orphan.table} ot"
            f"  LEFT JOIN {ref.table} rt"
            f"    ON ot.{orphan.column} = rt.{ref.column}"
            f"  WHERE rt.{ref.column} IS NULL"
            f"  LIMIT ?"
            ")"
        )
        return _run_batched_delete(db, sql, (), orphan_count, batch_size)

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
            logger.info(
                "⚠️  Skipping VACUUM — not enough disk space "
                "(DB: %.1f MB, free: %.1f MB, need: %.1f MB)",
                db_size_mb, free_space_mb,
                db_size_mb * VACUUM_SPACE_SAFETY_MARGIN,
            )
        return

    if dry_run:
        eta = db_size_mb / VACUUM_SPEED_ESTIMATE_MB_PER_SEC
        logger.info(
            "Would VACUUM (DB: %.1f MB, free: %.1f MB, est. %.0fs)",
            db_size_mb, free_space_mb, eta,
        )
        return

    t = _log_phase_start("VACUUM")
    logger.info("    DB size before: %s MB", format(db_size_mb, ".1f"))
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
        logger.info("✓ No database found, skipping")
        return (0, 0)

    purge_days, source = get_recorder_purge_days()
    logger.info("Using purge_keep_days: %s (from %s)", purge_days, source)
    cutoff_ts = int((datetime.now(tz=None) - timedelta(days=purge_days)).timestamp())  # noqa: DTZ005 — local time intentional

    try:
        # `with sqlite3.connect(...)` commits but does not close, and the WAL
        # only checkpoints once the connection is gone, so close it explicitly.
        conn = sqlite3.connect(DB_PATH)
        try:
            original_journal_mode = _set_journal_mode_wal(conn)
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
                    logger.info("✓ No old records to purge")
                    return (0, 0)

                if dry_run:
                    logger.info(
                        "Would purge %s states, %s events older than %d days",
                        f"{states:,}", f"{events:,}", purge_days,
                    )
                    _maybe_vacuum(dry_run=True)
                    return (states, events)

                logger.info(
                    "Purging %s states, %s events older than %d days",
                    f"{states:,}", f"{events:,}", purge_days,
                )

                db = _DbCtx(cur=cur, conn=conn)

                # Only `states` has a self-referencing FK needing an unlink.
                for phase, target, total in (
                    ("States", _TableRef("states", "last_updated_ts"), states),
                    ("Events", _TableRef("events", "time_fired_ts"), events),
                ):
                    if not total:
                        continue
                    t = _log_phase_start(phase)
                    if target.table == "states":
                        _unlink_old_state_ids(db, cutoff_ts)
                    deleted = _batch_delete_table(
                        db, target, cutoff_ts, total, _get_batch_size(total),
                    )
                    _log_phase_end(phase, t, f"deleted {deleted:,} rows")

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
                _checkpoint_and_restore_journal_mode(conn, original_journal_mode)
        finally:
            conn.close()

        # Phase 6: VACUUM (outside the transaction, connection closed)
        _maybe_vacuum()

    except sqlite3.Error as e:
        logger.info("⚠️  Database error: %s", e)
        return (0, 0)
    else:
        logger.info("✓ Database purged")
        return (states, events)


def cleanup_old_backups(dry_run: bool = False) -> int:
    """Remove backup files older than BACKUP_RETENTION_DAYS."""
    cutoff = (datetime.now(tz=None) - timedelta(days=BACKUP_RETENTION_DAYS)).timestamp()  # noqa: DTZ005 — local time intentional

    total_backups = 0
    files_to_remove: list[Path] = []
    for f in STORAGE_PATH.glob("*.backup.*"):
        total_backups += 1
        try:
            if f.stat().st_mtime < cutoff:
                files_to_remove.append(f)
        except OSError:
            pass

    if dry_run:
        if files_to_remove:
            logger.info("Would remove %s old backup files", len(files_to_remove))
        return len(files_to_remove)

    removed = 0
    for f in files_to_remove:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass

    if removed:
        logger.info(
            "✓ Removed %d old backup files (older than %d days)",
            removed, BACKUP_RETENTION_DAYS,
        )
    elif total_backups > 0:
        logger.info(
            "✓ No old backup files to remove "
            "(found %d backups, all within %d days)",
            total_backups, BACKUP_RETENTION_DAYS,
        )
    else:
        logger.info("✓ No backup files found")

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
            record_key = "devices" if file_type == "device_registry" else "entities"
            try:
                data = load_json(backup_path)
            except (ValueError, KeyError):
                # Corrupted file, skip
                logger.info("⚠️  Skipping corrupted backup: %s", backup_path.name)
                continue

            if not _has_record_list(data, record_key):
                logger.info(
                    "⚠️  Skipping corrupted backup: %s (no %s list)",
                    backup_path.name, record_key,
                )
                continue

            entity_count = len(_records(data, record_key))

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
            logger.info("⚠️  Error reading backup %s: %s", backup_path.name, e)
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
        for e in _records(backup_data, "entities")
    }
    current_entities = {
        e["entity_id"]: e
        for e in _records(current_data, "entities")
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
        backup_data = load_json(backup_info.path)
        current_data = load_json(ENTITY_REGISTRY)
    except (FileNotFoundError, ValueError) as e:
        logger.info("⚠️  Error loading registries: %s", e)
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
        logger.info("No entities selected, skipping")
        return None

    return [deleted[i - 1] for i in sorted(indices)]


def _restore_with_ha_stopped(
    build: Callable[[dict[str, Any]], tuple[dict[str, Any], int]],
) -> int:
    """Stop HA, back up the registry, build the new registry, save, restart HA.

    `build(fresh_data)` receives the registry re-read AFTER HA has stopped (the
    copy loaded before user interaction may be stale — HA could have written to
    it while the user reviewed a preview). It returns `(data_to_save, count)`:
    a selective restore mutates and returns `fresh_data`, a full restore returns
    the backup wholesale. This function owns the stop → backup → save → except
    scaffolding shared by both restore paths.
    """
    logger.info("Stopping Home Assistant...")
    try:
        with ha_stopped():
            backup_file(ENTITY_REGISTRY)
            fresh_data = load_json(ENTITY_REGISTRY)
            data_to_save, count = build(fresh_data)
            save_json(ENTITY_REGISTRY, data_to_save)
            return count
    except (RuntimeError, OSError, ValueError) as e:
        logger.info("⚠️  Restore failed: %s", e)
        return 0


def _apply_restore(selected_entities: list[dict[str, Any]]) -> int:
    """Perform the actual restore with HA stopped. Returns count restored."""
    def _merge(fresh_data: dict[str, Any]) -> tuple[dict[str, Any], int]:
        current_entity_ids = {
            e["entity_id"] for e in fresh_data["data"]["entities"]
        }
        restored_count = 0
        for entity in selected_entities:
            entity_id = entity.get("entity_id")
            if entity_id in current_entity_ids:
                logger.info("⚠️  Skipping %s (already exists)", entity_id)
                continue
            fresh_data["data"]["entities"].append(entity)
            restored_count += 1
        logger.info("✓ Restored %s entities", restored_count)
        return fresh_data, restored_count

    return _restore_with_ha_stopped(_merge)


def selective_restore_entities(backup_info: BackupInfo, dry_run: bool = False) -> int:
    """Restore selected entities from backup.

    Returns count of restored entities.
    """
    try:
        backup_data = load_json(backup_info.path)
        current_data = load_json(ENTITY_REGISTRY)
    except (FileNotFoundError, ValueError) as e:
        logger.info("⚠️  Error loading registries: %s", e)
        return 0

    diff = compare_registries(backup_data, current_data)
    if not diff.deleted:
        logger.info("✓ No deleted entities to restore")
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
        logger.info("DRY RUN: Would restore %s entities", len(selected_entities))
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
        backup_data = load_json(backup_info.path)
    except (FileNotFoundError, ValueError) as e:
        logger.info("⚠️  Error loading backup: %s", e)
        return 0

    if not _has_record_list(backup_data, "entities"):
        logger.info("⚠️  Invalid backup format: missing data.entities")
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
        logger.info("DRY RUN: Would restore %s entities", backup_entity_count)
        return backup_entity_count

    # Confirm action
    if not confirm_action("Fully restore registry from this backup?"):
        print("Aborted.")
        return 0

    def _overwrite(_fresh_data: dict[str, Any]) -> tuple[dict[str, Any], int]:
        # Full restore replaces the registry wholesale with the backup.
        logger.info("✓ Restored %s entities from backup", backup_entity_count)
        return backup_data, backup_entity_count

    return _restore_with_ha_stopped(_overwrite)


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


def _print_restore_menu(dry_run: bool) -> None:
    print("\n" + "=" * 70)
    mode = " [DRY RUN]" if dry_run else ""
    print(f"  Restore from Backup{mode}")
    print("=" * 70)
    print()
    print("  1. List available backups")
    print("  2. Preview backup differences")
    print("  3. Selective restore entities")
    print("  4. Full restore registry")
    print()
    print(f"  d. Toggle dry-run (currently {'ON' if dry_run else 'OFF'})")
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


def _dispatch_restore_action(
    choice: str,
    cached_backups: list[BackupInfo],
    dry_run: bool,
) -> bool:
    """Run the selected restore action. Returns True if cache should be invalidated."""
    if choice == "1":
        _list_backups_detailed(cached_backups)
        return False

    selected = _select_backup(cached_backups)
    if not selected:
        return False

    if choice == "2":
        preview_backup_diff(selected)
        return False
    if choice == "3":
        selective_restore_entities(selected, dry_run=dry_run)
    elif choice == "4":
        full_restore_registry(selected, dry_run=dry_run)
    return not dry_run


def restore_menu() -> None:
    """Interactive restore menu."""
    cached_backups: list[BackupInfo] | None = None
    dry_run = False

    while True:
        _print_restore_menu(dry_run)

        try:
            choice = input("  Select option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to main menu...")
            break

        if choice == "b":
            break
        if choice == "d":
            dry_run = not dry_run
            logger.info("✓ Dry-run mode %s", "ON" if dry_run else "OFF")
            continue
        if choice == "r":
            cached_backups = None
            logger.info("✓ Backup list refreshed")
            continue
        if choice not in {"1", "2", "3", "4"}:
            print("Invalid option, try again.")
            continue

        if cached_backups is None:
            cached_backups = scan_backup_files()
        if not cached_backups:
            logger.info("No backup files found")
            continue

        if _dispatch_restore_action(choice, cached_backups, dry_run):
            cached_backups = None


def _is_address_or_port_tail(base_id: str, tail: str) -> bool:
    """Check whether the numeric tail is part of an address or a port number.

    A MAC tail is a two-hex-digit group following another (`..._01_da_12`); a
    port is a number straight after `tcp` or `udp` (`..._dns_udp_53`). Network
    integrations produce plenty of both, and they look like duplicate suffixes.
    """
    previous_segment = base_id.rsplit("_", 1)[-1] if "_" in base_id else ""
    if (
        MAC_TAIL_SEGMENT_PATTERN.match(tail)
        and MAC_TAIL_SEGMENT_PATTERN.match(previous_segment)
    ):
        return True
    return bool(PORT_SUFFIX_BASE_PATTERN.search(base_id))


def find_suffix_entities() -> list[tuple[str, str, str]]:
    """Find entities with numeric suffix (_2, _3, etc.) that might be duplicates.

    Returns list of tuples: (old_id, new_id, platform)

    Candidates end in `_2`-`_99`, have no entity holding the base ID, no
    `<base>_1` sibling, and no MAC or port tail. Survivors can still be
    legitimate (button_4, pm2_5), so the caller confirms each one.
    """
    if not ENTITY_REGISTRY.exists():
        return []

    try:
        data = load_json(ENTITY_REGISTRY)
    except (FileNotFoundError, ValueError):
        return []

    entities = _records(data, "entities")

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

        # A `<base>_1` sibling means the device numbered these itself, since
        # Home Assistant never emits `_1`.
        if f"{new_id}_1" in all_entity_ids:
            continue

        if _is_address_or_port_tail(new_id, match.group(1)):
            continue

        candidates.append((entity_id, new_id, platform))

    # Exclude candidates where multiple suffixed entities map to the same base.
    # Renaming both would create duplicate entity_ids — registry corruption.
    target_counts: dict[str, int] = {}
    for _old, new_id, _platform in candidates:
        target_counts[new_id] = target_counts.get(new_id, 0) + 1

    kept = [c for c in candidates if target_counts[c[1]] == 1]
    excluded = [c for c in candidates if target_counts[c[1]] > 1]

    if excluded:
        groups: dict[str, list[str]] = {}
        for old_id, new_id, _platform in excluded:
            groups.setdefault(new_id, []).append(old_id)
        for base, olds in groups.items():
            logger.warning(
                "Skipping %d collision candidates for %s — "
                "rename manually one at a time: %s",
                len(olds), base, ", ".join(sorted(olds)),
            )

    return kept


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
        logger.info("⚠️  Ignored invalid selection parts: %s", ', '.join(skipped))
    return indices


def fix_entity_suffix(dry_run: bool = False) -> int:
    """Fix numeric suffix in entity registry with interactive selection."""
    candidates = find_suffix_entities()

    if not candidates:
        logger.info("✓ No numeric suffix entities found")
        return 0

    # In dry-run mode, just list all candidates
    if dry_run:
        logger.info("Found %s entities with numeric suffix:", len(candidates))
        for old_id, new_id, platform in candidates:
            logger.info("  - %s -> %s (%s)", old_id, new_id, platform)
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
        logger.info("No entities selected, skipping")
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
    logger.info("✓ Fixed %s entity suffixes", len(selected_fixes))
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
    print("  1. Full cleanup (options 2-4, 6 — optimised)")
    print("  2. Remove orphaned entities (missing device/config/definition)")
    print("  3. Clean deleted registry items (deleted_entities/devices)")
    print("  4. Purge old database records (optimised batch + progress)")
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

    logger.info("Stopping Home Assistant...")
    try:
        with ha_stopped():
            for op in operations:
                try:
                    op(dry_run=False)
                except (OSError, ValueError, sqlite3.Error) as e:
                    logger.info("⚠️  Error in %s: %s", op.__name__, e)
            cleanup_old_backups()

            db_after = get_db_size()
            if db_before and db_after:
                saved = db_before - db_after
                if saved > 0:
                    logger.info(
                        "Database: %.1f MB → %.1f MB (%.1f MB saved)",
                        db_before, db_after, saved,
                    )
    except RuntimeError:
        return

    logger.info("Done!")


def _run_dry_run_preview() -> None:
    print("\n" + "=" * 70)
    logger.info("DRY RUN - Preview all changes")
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
        logger.info("✓ No numeric suffix entities found")
        return

    if not confirm_action("This will stop Home Assistant. Continue?"):
        print("Aborted.")
        return

    logger.info("Stopping Home Assistant...")
    try:
        with ha_stopped():
            fix_entity_suffix(dry_run=False)
    except (RuntimeError, OSError, ValueError) as e:
        logger.info("⚠️  Suffix fix failed: %s", e)
        return
    logger.info("Done!")


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
        logger.info("=" * 50)
        logger.info("Home Assistant Cleanup (DRY RUN)")
        logger.info("=" * 50)
        logger.info("Config path: %s", CONFIG_PATH)
        db_size = get_db_size()
        if db_size:
            logger.info("Database size: %s MB\n", format(db_size, ".1f"))
        orphans = cleanup_orphaned_entities(dry_run=True)
        deleted = cleanup_deleted_items(dry_run=True)
        states, events = purge_database(dry_run=True)
        suffix = fix_entity_suffix(dry_run=True)
        old_backups = cleanup_old_backups(dry_run=True)

        logger.info("%s", "\n" + "=" * 50)
        logger.info("Summary:")
        logger.info("  Orphaned entities: %s", orphans)
        logger.info("  Deleted registry items: %s", deleted)
        logger.info("  DB states to purge: %s", format(states, ","))
        logger.info("  DB events to purge: %s", format(events, ","))
        logger.info("  Suffix fixes: %s", suffix)
        logger.info("  Old backup files: %s", old_backups)
        logger.info("=" * 50)
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
