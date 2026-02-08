#!/usr/bin/env python3
"""
Home Assistant Cleanup Tool
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
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# ============================================================
# Configuration
# ============================================================

# Auto-detect config path
CONFIG_PATHS = ["/homeassistant", "/config", Path.home() / ".homeassistant"]
CONFIG_PATH = next((Path(p) for p in CONFIG_PATHS if Path(p).exists()), None)

if not CONFIG_PATH:
    logger.error("Could not find Home Assistant config directory")
    sys.exit(1)

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

# Regex patterns (compiled at module level for performance)
NUMERIC_SUFFIX_PATTERN = re.compile(r'_(\d+)$')
YAML_ID_PATTERN = re.compile(r'(?:^|\n)\s*-?\s*id:\s*["\']?([^"\'\n\r]+)["\']?')
BACKUP_PATTERN = re.compile(r'\.backup\.(\d{8}_\d{6})$')
DUPLICATE_SUFFIX_PATTERN = re.compile(r'_([2-9]|\d{2,})$')


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
    deleted: list[dict]      # In backup but not in current
    new: list[dict]          # In current but not in backup
    modified: list[tuple]    # (backup_entity, current_entity)


# ============================================================
# Simple Cache for JSON files
# ============================================================

_json_cache: dict[Path, tuple[float, dict]] = {}  # path -> (mtime, data)


def _get_cached_json(path: Path) -> dict | None:
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


def _cache_json(path: Path, data: dict) -> None:
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
        raise FileNotFoundError(f"Cannot backup non-existent file: {path}")
    backup = Path(f"{path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(path, backup)
    return backup


def load_json(path: Path, use_cache: bool = True) -> dict:
    """Load JSON file with error handling and optional caching."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    
    # Check cache first
    if use_cache:
        cached = _get_cached_json(path)
        if cached is not None:
            return cached
    
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
            if use_cache:
                _cache_json(path, data)
            return data
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}")


def save_json(path: Path, data: dict) -> None:
    """
    Save data to JSON file with atomic write and file locking.
    
    This prevents race conditions when HA might be writing to the same file.
    Uses a temporary file + atomic rename pattern.
    """
    temp_path = Path(f"{path}.tmp.{os.getpid()}")
    
    try:
        with open(temp_path, 'w', encoding='utf-8') as f:
            # Acquire exclusive lock (blocks if HA is writing)
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())  # Force write to disk
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        
        # Atomic rename (POSIX guarantees atomicity)
        temp_path.replace(path)
        
        # Invalidate cache after write
        invalidate_cache(path)
        
    except Exception as e:
        # Clean up temp file on error
        if temp_path.exists():
            temp_path.unlink()
        raise ValueError(f"Failed to save JSON to {path}: {e}")


def get_db_size() -> float:
    """Get database size in MB."""
    if DB_PATH.exists():
        return DB_PATH.stat().st_size / (1024 * 1024)
    return 0.0


def stop_ha() -> str | None:
    """Stop Home Assistant using available method."""
    methods = [
        (["ha", "core", "stop"], "ha"),
        (["systemctl", "stop", "home-assistant@homeassistant"], "systemctl"),
        (["docker", "stop", "homeassistant"], "docker"),
    ]
    for cmd, method in methods:
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=60)
            return method
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            continue
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
    try:
        subprocess.run(cmds[method], check=True, capture_output=True, timeout=60)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def get_recorder_purge_days() -> int:
    """Get purge_keep_days from HA recorder config, fallback to default."""
    # Try configuration.yaml first
    config_yaml = CONFIG_PATH / "configuration.yaml"
    if config_yaml.exists():
        try:
            content = config_yaml.read_text(encoding='utf-8')
            # Simple regex to find purge_keep_days in recorder section
            # This handles most common YAML formats
            match = re.search(
                r'recorder:\s*\n(?:.*\n)*?\s+purge_keep_days:\s*(\d+)',
                content,
                re.MULTILINE
            )
            if match:
                return int(match.group(1))
        except (IOError, ValueError):
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

def extract_ids_from_yaml_file(path: Path) -> set:
    """Extract IDs from a YAML file using regex."""
    ids = set()
    if not path.exists():
        return ids
    
    try:
        content = path.read_text(encoding='utf-8')
        # Use pre-compiled pattern
        for match in YAML_ID_PATTERN.finditer(content):
            id_value = match.group(1).strip()
            if id_value and not id_value.startswith('#'):
                ids.add(id_value)
    except IOError:
        pass
    
    return ids


def get_entity_ids(entity_type: str, folder_path: Path, yaml_file: str, storage_file: str) -> set:
    """
    Generic function to get entity IDs from YAML files and UI storage.
    
    Args:
        entity_type: Type of entity (automation, script, scene)
        folder_path: Path to folder containing YAML files
        yaml_file: Name of root YAML file (e.g., "automations.yaml")
        storage_file: Name of storage file (e.g., "automations")
    
    Returns:
        Set of entity IDs
    """
    ids = set()
    
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


def get_automation_ids() -> set:
    """Get all automation IDs from YAML files and UI storage."""
    return get_entity_ids("automation", AUTOMATION_PATH, "automations.yaml", "automations")


def get_script_ids() -> set:
    """Get all script IDs from YAML files and UI storage."""
    return get_entity_ids("script", SCRIPT_PATH, "scripts.yaml", "scripts")


def get_scene_ids() -> set:
    """Get all scene IDs from YAML files and UI storage."""
    return get_entity_ids("scene", SCENE_PATH, "scenes.yaml", "scenes")



# ============================================================
# Cleanup Functions
# ============================================================

def find_orphaned_entities() -> list:
    """
    Find entities with missing device, config_entry, or definition.
    
    Returns list of tuples: (platform, entity_id, name)
    """
    # Check required files exist
    if not ENTITY_REGISTRY.exists():
        log("⚠️  Entity registry not found, skipping orphan detection")
        return []
    if not DEVICE_REGISTRY.exists():
        log("⚠️  Device registry not found, skipping orphan detection")
        return []
    if not CONFIG_ENTRIES.exists():
        log("⚠️  Config entries not found, skipping orphan detection")
        return []
    
    try:
        entity_data = load_json(ENTITY_REGISTRY)
        device_data = load_json(DEVICE_REGISTRY)
        config_data = load_json(CONFIG_ENTRIES)
    except (FileNotFoundError, ValueError) as e:
        log(f"⚠️  Error loading registry files: {e}")
        return []
    
    # Build lookup sets (use set comprehension for better performance)
    devices = {d["id"] for d in device_data.get("data", {}).get("devices", [])}
    config_entries = {e["entry_id"] for e in config_data.get("data", {}).get("entries", [])}
    
    # Get IDs for automation, script, scene
    automation_ids = get_automation_ids()
    script_ids = get_script_ids()
    scene_ids = get_scene_ids()
    
    orphans = []
    for entity in entity_data.get('data', {}).get('entities', []):
        platform = entity.get('platform', '')
        entity_id = entity.get('entity_id', '')
        device_id = entity.get('device_id')
        config_entry_id = entity.get('config_entry_id')
        unique_id = entity.get('unique_id')
        name = entity.get('original_name', '')
        
        is_orphan = False
        
        # Check device reference
        if device_id and device_id not in devices:
            is_orphan = True
        
        # Check config entry reference
        if config_entry_id and config_entry_id not in config_entries:
            is_orphan = True
        
        # Special handling for automation/script/scene
        # Only mark as orphan if unique_id exists AND not found in definitions
        if platform == 'automation':
            if unique_id:
                is_orphan = unique_id not in automation_ids
            else:
                is_orphan = False  # Can't verify, don't delete
        elif platform == 'script':
            if unique_id:
                is_orphan = unique_id not in script_ids
            else:
                is_orphan = False
        elif platform == 'scene':
            if unique_id:
                is_orphan = unique_id not in scene_ids
            else:
                is_orphan = False
        
        if is_orphan:
            orphans.append((platform, entity_id, name))
    
    return orphans


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
    data = load_json(ENTITY_REGISTRY)
    original_count = len(data['data']['entities'])
    data['data']['entities'] = [
        e for e in data['data']['entities'] 
        if e.get('entity_id') not in orphan_eids
    ]
    new_count = len(data['data']['entities'])
    
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
        
        deleted_items = data.get('data', {}).get(key, [])
        n = len(deleted_items)
        
        if n > 0:
            if dry_run:
                log(f"Would clean {n} {key.replace('_', ' ')}")
            else:
                backup_file(path)
                data['data'][key] = []
                save_json(path, data)
                log(f"✓ Cleaned {n} {key.replace('_', ' ')}")
            count += n
    
    if count == 0:
        log("✓ No deleted registry items to clean")
    
    return count


def purge_database(dry_run: bool = False) -> tuple:
    """Purge old database records and vacuum."""
    if not DB_PATH.exists():
        log("✓ No database found, skipping")
        return (0, 0)
    
    purge_days = get_recorder_purge_days()
    log(f"Using purge_keep_days: {purge_days}")
    
    cutoff_ts = int((datetime.now() - timedelta(days=purge_days)).timestamp())
    
    # Use context manager for proper connection handling
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cur = conn.cursor()
            
            # Count records to purge
            cur.execute("SELECT COUNT(*) FROM states WHERE last_updated_ts < ?", (cutoff_ts,))
            states = cur.fetchone()[0]
            
            cur.execute("SELECT COUNT(*) FROM events WHERE time_fired_ts < ?", (cutoff_ts,))
            events = cur.fetchone()[0]
            
            if states or events:
                log(f"{'Would purge' if dry_run else 'Purging'} {states} states, {events} events older than {purge_days} days")
                
                if not dry_run:
                    # Execute all deletes in single transaction (already in context manager)
                    cur.execute("DELETE FROM states WHERE last_updated_ts < ?", (cutoff_ts,))
                    cur.execute("DELETE FROM events WHERE time_fired_ts < ?", (cutoff_ts,))
                    
                    # Clean orphaned attributes and event data in same transaction
                    cur.execute("""
                        DELETE FROM state_attributes 
                        WHERE NOT EXISTS (
                            SELECT 1 FROM states 
                            WHERE states.attributes_id = state_attributes.attributes_id
                        )
                    """)
                    cur.execute("""
                        DELETE FROM event_data 
                        WHERE NOT EXISTS (
                            SELECT 1 FROM events 
                            WHERE events.data_id = event_data.data_id
                        )
                    """)
                    
                    # Commit all changes at once
                    conn.commit()
                    
                    # Vacuum after commit
                    conn.execute("VACUUM")
                    log("✓ Database purged and vacuumed")
            else:
                log("✓ No old records to purge")
            
            return (states, events)
            
    except sqlite3.Error as e:
        log(f"⚠️  Database error: {e}")
        return (0, 0)


def cleanup_old_backups() -> int:
    """Remove backup files older than BACKUP_RETENTION_DAYS."""
    cutoff = (datetime.now() - timedelta(days=BACKUP_RETENTION_DAYS)).timestamp()
    removed = 0
    
    # Count total backup files
    total_backups = len(list(STORAGE_PATH.glob("*.backup.*")))
    
    # Batch collect files to remove (avoid multiple stat calls)
    files_to_remove = []
    for f in STORAGE_PATH.glob("*.backup.*"):
        try:
            if f.stat().st_mtime < cutoff:
                files_to_remove.append(f)
        except OSError:
            pass
    
    # Remove collected files
    for f in files_to_remove:
        try:
            f.unlink()
            removed += 1
        except OSError:
            pass
    
    if removed:
        log(f"✓ Removed {removed} old backup files (older than {BACKUP_RETENTION_DAYS} days)")
    else:
        if total_backups > 0:
            log(f"✓ No old backup files to remove (found {total_backups} backups, all within {BACKUP_RETENTION_DAYS} days)")
        else:
            log("✓ No backup files found")
    
    return removed


# ============================================================
# Restore Functions
# ============================================================

def scan_backup_files() -> list[BackupInfo]:
    """
    Scan .storage/ folder for backup files.

    Returns list of BackupInfo sorted by timestamp (newest first).
    """
    backups = []

    for backup_file in STORAGE_PATH.glob("*.backup.*"):
        try:
            # Get file stats once (optimization: avoid multiple stat() calls)
            file_stat = backup_file.stat()

            # Parse timestamp from filename using pre-compiled pattern
            match = BACKUP_PATTERN.search(backup_file.name)
            if not match:
                # Fallback to file mtime if timestamp not in filename
                timestamp = datetime.fromtimestamp(file_stat.st_mtime)
            else:
                timestamp_str = match.group(1)
                timestamp = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')

            # Determine file type
            if 'entity_registry' in backup_file.name:
                file_type = 'entity_registry'
            elif 'device_registry' in backup_file.name:
                file_type = 'device_registry'
            else:
                file_type = 'unknown'

            # Load JSON and count entities
            try:
                data = load_json(backup_file, use_cache=False)  # Don't cache backups
                entity_count = len(data.get('data', {}).get('entities', []))
            except (ValueError, KeyError):
                # Corrupted file, skip
                log(f"⚠️  Skipping corrupted backup: {backup_file.name}")
                continue

            # Calculate file size (use cached stat)
            size_mb = file_stat.st_size / (1024 * 1024)

            backups.append(BackupInfo(
                path=backup_file,
                timestamp=timestamp,
                file_type=file_type,
                size_mb=size_mb,
                entity_count=entity_count
            ))

        except (OSError, ValueError) as e:
            log(f"⚠️  Error reading backup {backup_file.name}: {e}")
            continue

    # Sort by timestamp (newest first)
    backups.sort(key=lambda b: b.timestamp, reverse=True)

    return backups


def compare_registries(backup_data: dict, current_data: dict) -> EntityDiff:
    """
    Compare backup and current registry to find differences.

    Returns EntityDiff with deleted, new, and modified entities.
    """
    # Build entity_id -> entity dict for both registries
    backup_entities = {
        e['entity_id']: e
        for e in backup_data.get('data', {}).get('entities', [])
    }
    current_entities = {
        e['entity_id']: e
        for e in current_data.get('data', {}).get('entities', [])
    }

    backup_ids = set(backup_entities.keys())
    current_ids = set(current_entities.keys())

    # Find deleted entities (in backup but not in current)
    deleted = [backup_entities[eid] for eid in (backup_ids - current_ids)]

    # Find new entities (in current but not in backup)
    new = [current_entities[eid] for eid in (current_ids - backup_ids)]

    # Find modified entities (compare attributes for common entity_ids)
    # Use set of attributes to compare for faster comparison
    attrs_to_compare = {'platform', 'device_id', 'config_entry_id', 'original_name', 'disabled_by'}
    modified = []
    common_ids = backup_ids & current_ids

    for eid in common_ids:
        backup_entity = backup_entities[eid]
        current_entity = current_entities[eid]

        # Quick comparison using any() for early exit
        if any(backup_entity.get(attr) != current_entity.get(attr) for attr in attrs_to_compare):
            modified.append((backup_entity, current_entity))

    return EntityDiff(deleted=deleted, new=new, modified=modified)


def preview_backup_diff(backup_info: BackupInfo) -> None:
    """
    Display differences between backup and current registry.
    """
    # Load backup and current registry
    try:
        backup_data = load_json(backup_info.path, use_cache=False)
        current_data = load_json(ENTITY_REGISTRY)
    except (FileNotFoundError, ValueError) as e:
        log(f"⚠️  Error loading registries: {e}")
        return

    # Compare registries
    diff = compare_registries(backup_data, current_data)

    # Display backup metadata
    print(f"\nBackup: {backup_info.path.name}")
    print(f"Timestamp: {backup_info.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Entities in backup: {backup_info.entity_count}")
    print()

    # Display deleted entities
    print("=" * 60)
    print(f"DELETED ENTITIES (in backup but not in current): {len(diff.deleted)}")
    print("=" * 60)
    if diff.deleted:
        for i, entity in enumerate(diff.deleted, 1):
            entity_id = entity.get('entity_id', 'unknown')
            platform = entity.get('platform', 'unknown')
            name = entity.get('original_name', '')
            print(f"  {i:2d}. {entity_id} ({platform})")
            if name:
                print(f"      Name: {name}")
    else:
        print("  None")
    print()

    # Display new entities
    print("=" * 60)
    print(f"NEW ENTITIES (in current but not in backup): {len(diff.new)}")
    print("=" * 60)
    if diff.new:
        for i, entity in enumerate(diff.new, 1):
            entity_id = entity.get('entity_id', 'unknown')
            platform = entity.get('platform', 'unknown')
            print(f"  {i:2d}. {entity_id} ({platform})")
    else:
        print("  None")
    print()

    # Display modified entities
    print("=" * 60)
    print(f"MODIFIED ENTITIES: {len(diff.modified)}")
    print("=" * 60)
    if diff.modified:
        for i, (backup_entity, current_entity) in enumerate(diff.modified, 1):
            entity_id = backup_entity.get('entity_id', 'unknown')
            print(f"  {i:2d}. {entity_id}")

            # Show what changed (use set for faster lookup)
            attrs = {'platform', 'device_id', 'config_entry_id', 'original_name', 'disabled_by'}
            for attr in attrs:
                backup_val = backup_entity.get(attr)
                current_val = current_entity.get(attr)
                if backup_val != current_val:
                    print(f"      {attr}: {backup_val} → {current_val}")
    else:
        print("  None")
    print()


def selective_restore_entities(backup_info: BackupInfo, dry_run: bool = False) -> int:
    """
    Restore selected entities from backup.

    Returns count of restored entities.
    """
    # Load backup and current registry
    try:
        backup_data = load_json(backup_info.path, use_cache=False)
        current_data = load_json(ENTITY_REGISTRY)
    except (FileNotFoundError, ValueError) as e:
        log(f"⚠️  Error loading registries: {e}")
        return 0

    # Compare registries to find deleted entities
    diff = compare_registries(backup_data, current_data)

    if not diff.deleted:
        log("✓ No deleted entities to restore")
        return 0

    # Display deleted entities with numbering
    print(f"\nFound {len(diff.deleted)} deleted entities:")
    print("=" * 60)
    for i, entity in enumerate(diff.deleted, 1):
        entity_id = entity.get('entity_id', 'unknown')
        platform = entity.get('platform', 'unknown')
        name = entity.get('original_name', '')
        print(f"  [{i:2d}] {entity_id} ({platform})")
        if name:
            print(f"       Name: {name}")
    print()

    # Prompt user for selection
    print("Enter selection:")
    print("  - Numbers: 1,3,5 or 1-5 or 1,3-5,8")
    print("  - 'all' to restore all")
    print("  - 'none' or Enter to skip")
    print()

    try:
        selection = input("Selection: ")
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return 0

    indices = parse_selection(selection, len(diff.deleted))

    if not indices:
        log("No entities selected, skipping")
        return 0

    # Get selected entities
    selected_entities = [diff.deleted[i - 1] for i in sorted(indices)]

    # Display selected entities and confirm
    print(f"\nWill restore {len(selected_entities)} entities:")
    for entity in selected_entities:
        entity_id = entity.get('entity_id', 'unknown')
        platform = entity.get('platform', 'unknown')
        print(f"  - {entity_id} ({platform})")
    print()

    if dry_run:
        log(f"DRY RUN: Would restore {len(selected_entities)} entities")
        return len(selected_entities)

    if not confirm_action(f"Restore these {len(selected_entities)} entities?"):
        print("Aborted.")
        return 0

    # Stop HA
    log("Stopping Home Assistant...")
    method = stop_ha()
    if not method:
        log("⚠️  Could not stop HA automatically.")
        if not confirm_action("Please stop HA manually. Continue when stopped?"):
            return 0

    time.sleep(HA_STOP_WAIT_SECONDS)

    try:
        # Backup current registry
        backup_file(ENTITY_REGISTRY)

        # Merge selected entities into current registry
        current_entity_ids = {e['entity_id'] for e in current_data['data']['entities']}
        restored_count = 0

        for entity in selected_entities:
            entity_id = entity.get('entity_id')
            if entity_id in current_entity_ids:
                log(f"⚠️  Skipping {entity_id} (already exists)")
                continue

            current_data['data']['entities'].append(entity)
            restored_count += 1

        # Save registry
        save_json(ENTITY_REGISTRY, current_data)
        log(f"✓ Restored {restored_count} entities")

        return restored_count

    finally:
        # Start HA
        log("Starting Home Assistant...")
        if method:
            if not start_ha(method):
                log("⚠️  Failed to start HA. Please start manually.")
        else:
            log("Please start Home Assistant manually.")


def full_restore_registry(backup_info: BackupInfo, dry_run: bool = False) -> int:
    """
    Fully restore registry from backup.

    Returns entity count from backup.
    """
    # Load and validate backup file
    try:
        backup_data = load_json(backup_info.path, use_cache=False)
    except (FileNotFoundError, ValueError) as e:
        log(f"⚠️  Error loading backup: {e}")
        return 0

    # Check data.entities exists
    if 'data' not in backup_data or 'entities' not in backup_data['data']:
        log("⚠️  Invalid backup format: missing data.entities")
        return 0

    backup_entity_count = len(backup_data['data']['entities'])

    # Load current registry and count entities
    try:
        current_data = load_json(ENTITY_REGISTRY)
        current_entity_count = len(current_data['data']['entities'])
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
        diff_percent = abs(backup_entity_count - current_entity_count) / current_entity_count * 100
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
    method = stop_ha()
    if not method:
        log("⚠️  Could not stop HA automatically.")
        if not confirm_action("Please stop HA manually. Continue when stopped?"):
            return 0

    time.sleep(HA_STOP_WAIT_SECONDS)

    try:
        # Backup current registry
        backup_file(ENTITY_REGISTRY)

        # Copy backup file to registry path
        shutil.copy2(backup_info.path, ENTITY_REGISTRY)
        log(f"✓ Restored {backup_entity_count} entities from backup")

        return backup_entity_count

    finally:
        # Start HA
        log("Starting Home Assistant...")
        if method:
            if not start_ha(method):
                log("⚠️  Failed to start HA. Please start manually.")
        else:
            log("Please start Home Assistant manually.")


def restore_menu() -> None:
    """Interactive restore menu."""
    # Cache backups list to avoid repeated scanning
    cached_backups = None
    
    while True:
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

        try:
            choice = input("  Select option: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nReturning to main menu...")
            break

        if choice == 'b':
            break
        
        elif choice == 'r':
            # Refresh backup list
            cached_backups = None
            log("✓ Backup list refreshed")
            continue

        elif choice == '1':
            # List available backups
            if cached_backups is None:
                cached_backups = scan_backup_files()
            
            if not cached_backups:
                log("No backup files found")
                continue

            print(f"\nFound {len(cached_backups)} backup files:")
            print("=" * 60)
            print(f"{'#':<4} {'Timestamp':<20} {'Type':<18} {'Entities':<10} {'Size (MB)':<10}")
            print("-" * 60)

            for i, backup in enumerate(cached_backups, 1):
                timestamp_str = backup.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                print(f"{i:<4} {timestamp_str:<20} {backup.file_type:<18} {backup.entity_count:<10} {backup.size_mb:<10.2f}")
            print()

        elif choice == '2':
            # Preview backup differences
            if cached_backups is None:
                cached_backups = scan_backup_files()
            
            if not cached_backups:
                log("No backup files found")
                continue

            # Show list
            print(f"\nAvailable backups:")
            for i, backup in enumerate(cached_backups, 1):
                timestamp_str = backup.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                print(f"  [{i}] {timestamp_str} - {backup.file_type} ({backup.entity_count} entities)")
            print()

            try:
                selection = input("Select backup number (or Enter to cancel): ").strip()
                if not selection:
                    continue

                idx = int(selection) - 1
                if 0 <= idx < len(cached_backups):
                    preview_backup_diff(cached_backups[idx])
                else:
                    print("Invalid selection")
            except (ValueError, EOFError, KeyboardInterrupt):
                print("Invalid selection")

        elif choice == '3':
            # Selective restore entities
            if cached_backups is None:
                cached_backups = scan_backup_files()
            
            if not cached_backups:
                log("No backup files found")
                continue

            # Show list
            print(f"\nAvailable backups:")
            for i, backup in enumerate(cached_backups, 1):
                timestamp_str = backup.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                print(f"  [{i}] {timestamp_str} - {backup.file_type} ({backup.entity_count} entities)")
            print()

            try:
                selection = input("Select backup number (or Enter to cancel): ").strip()
                if not selection:
                    continue

                idx = int(selection) - 1
                if 0 <= idx < len(cached_backups):
                    selective_restore_entities(cached_backups[idx])
                    # Invalidate cache after restore
                    cached_backups = None
                    invalidate_cache()
                else:
                    print("Invalid selection")
            except (ValueError, EOFError, KeyboardInterrupt):
                print("Invalid selection")

        elif choice == '4':
            # Full restore registry
            if cached_backups is None:
                cached_backups = scan_backup_files()
            
            if not cached_backups:
                log("No backup files found")
                continue

            # Show list
            print(f"\nAvailable backups:")
            for i, backup in enumerate(cached_backups, 1):
                timestamp_str = backup.timestamp.strftime('%Y-%m-%d %H:%M:%S')
                print(f"  [{i}] {timestamp_str} - {backup.file_type} ({backup.entity_count} entities)")
            print()

            try:
                selection = input("Select backup number (or Enter to cancel): ").strip()
                if not selection:
                    continue

                idx = int(selection) - 1
                if 0 <= idx < len(cached_backups):
                    full_restore_registry(cached_backups[idx])
                    # Invalidate cache after restore
                    cached_backups = None
                    invalidate_cache()
                else:
                    print("Invalid selection")
            except (ValueError, EOFError, KeyboardInterrupt):
                print("Invalid selection")

        else:
            print("Invalid option, try again.")








def find_suffix_entities() -> list:
    """
    Find entities with numeric suffix (_2, _3, etc.) that might be duplicates.
    
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
    
    return candidates


def parse_selection(selection: str, max_num: int) -> set:
    """
    Parse user selection string into set of indices.
    
    Supports:
    - Single numbers: "1", "5"
    - Comma-separated: "1,3,5"
    - Ranges: "1-5"
    - Mixed: "1,3-5,8"
    - Special: "all", "none", ""
    """
    selection = selection.strip().lower()
    
    # Early return for special cases
    if selection in ('', 'none', 'n', 'q'):
        return set()
    
    if selection == 'all':
        return set(range(1, max_num + 1))
    
    indices = set()
    parts = selection.replace(' ', '').split(',')
    
    for part in parts:
        if not part:
            continue
        
        if '-' in part:
            # Range: "1-5"
            try:
                start, end = part.split('-', 1)
                start = int(start)
                end = int(end)
                indices.update(range(start, end + 1))
            except ValueError:
                pass
        else:
            # Single number
            try:
                num = int(part)
                if 1 <= num <= max_num:
                    indices.add(num)
            except ValueError:
                pass
    
    # Filter out invalid indices
    return {i for i in indices if 1 <= i <= max_num}


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
    for old_id, new_id, platform in selected_fixes:
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
    print("  Home Assistant Cleanup Tool")
    print("=" * 70)
    print(f"  Config: {CONFIG_PATH}")
    db_size = get_db_size()
    if db_size:
        print(f"  Database: {db_size:.1f} MB")
    print("=" * 70)
    print()
    print("  1. Full cleanup (options 2-4, 6)")
    print("  2. Remove orphaned entities (missing device/config/definition)")
    print("  3. Clean deleted registry items (deleted_entities/devices)")
    print(f"  4. Purge old database records (auto-detect purge_keep_days)")
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
        return response.lower() == 'y'
    except (EOFError, KeyboardInterrupt):
        return False


def run_with_ha_restart(operations: list, dry_run: bool = False) -> None:
    """Run operations that require HA restart."""
    if dry_run:
        for op in operations:
            op(dry_run=True)
        return
    
    if not confirm_action("This will stop Home Assistant. Continue?"):
        print("Aborted.")
        return
    
    log("Stopping Home Assistant...")
    method = stop_ha()
    if not method:
        log("⚠️  Could not stop HA automatically.")
        if not confirm_action("Please stop HA manually. Continue when stopped?"):
            return
    
    # Wait for HA to fully stop
    time.sleep(HA_STOP_WAIT_SECONDS)
    
    db_before = get_db_size()
    
    try:
        for op in operations:
            try:
                op(dry_run=False)
            except Exception as e:
                log(f"⚠️  Error in {op.__name__}: {e}")
        
        cleanup_old_backups()
        
        db_after = get_db_size()
        if db_before and db_after:
            saved = db_before - db_after
            if saved > 0:
                log(f"Database: {db_before:.1f} MB → {db_after:.1f} MB ({saved:.1f} MB saved)")
    
    finally:
        # Invalidate cache after operations
        invalidate_cache()
        
        log("Starting Home Assistant...")
        if method:
            if not start_ha(method):
                log("⚠️  Failed to start HA automatically. Please start manually.")
        else:
            log("Please start Home Assistant manually.")
    
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

        if choice == 'q':
            print("Bye!")
            break
        elif choice == 'd':
            print("\n" + "=" * 70)
            log("DRY RUN - Preview all changes")
            print("=" * 70 + "\n")
            cleanup_orphaned_entities(dry_run=True)
            cleanup_deleted_items(dry_run=True)
            purge_database(dry_run=True)
            fix_entity_suffix(dry_run=True)
        elif choice == '1':
            # Full cleanup - but suffix fix is separate due to interactive nature
            run_with_ha_restart([
                cleanup_orphaned_entities,
                cleanup_deleted_items,
                purge_database,
            ])
            print("\n⚠️  Suffix fix requires manual selection. Run option 5 separately.")
        elif choice == '2':
            run_with_ha_restart([cleanup_orphaned_entities])
        elif choice == '3':
            run_with_ha_restart([cleanup_deleted_items])
        elif choice == '4':
            run_with_ha_restart([purge_database])
        elif choice == '5':
            # Suffix fix is interactive, needs special handling
            candidates = find_suffix_entities()
            if not candidates:
                log("✓ No numeric suffix entities found")
                continue

            if not confirm_action("This will stop Home Assistant. Continue?"):
                print("Aborted.")
                continue

            log("Stopping Home Assistant...")
            method = stop_ha()
            if not method:
                log("⚠️  Could not stop HA automatically.")
                if not confirm_action("Please stop HA manually. Continue when stopped?"):
                    continue
            time.sleep(HA_STOP_WAIT_SECONDS)

            try:
                fix_entity_suffix(dry_run=False)
            finally:
                # Invalidate cache after suffix fix
                invalidate_cache()
                
                log("Starting Home Assistant...")
                if method:
                    if not start_ha(method):
                        log("⚠️  Failed to start HA. Please start manually.")
                else:
                    log("Please start Home Assistant manually.")
            log("Done!")
        elif choice == '6':
            cleanup_old_backups()
        elif choice == '7':
            restore_menu()
        else:
            print("Invalid option, try again.")


# ============================================================
# Main Entry Point
# ============================================================

def main() -> None:
    """Main entry point."""
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
        
        log("\n" + "=" * 50)
        log("Summary:")
        log(f"  Orphaned entities: {orphans}")
        log(f"  Deleted registry items: {deleted}")
        log(f"  Suffix fixes: {suffix}")
        log("=" * 50)
    else:
        interactive_menu()








if __name__ == "__main__":
    main()
