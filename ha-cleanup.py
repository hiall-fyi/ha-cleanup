#!/usr/bin/env python3
"""
Home Assistant Cleanup Tool
Interactive menu for various cleanup operations.

Features:
  - Remove orphaned entities (missing device/config/automation/script/scene)
  - Fix numeric suffix issues (_2, _3, etc.) on entity IDs
  - Clean deleted_entities and deleted_devices from registries
  - Purge old states/events and vacuum database
  - Auto-detects recorder purge_keep_days from HA config
  - Auto-detects config path (HAOS, Docker, Core)

Usage:
  python3 ha-cleanup.py              # Interactive menu
  python3 ha-cleanup.py --dry-run    # Preview all changes
"""
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import time
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

# Regex pattern for numeric suffix (e.g., _2, _3, _10)
NUMERIC_SUFFIX_PATTERN = re.compile(r'_(\d+)$')


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


def load_json(path: Path) -> dict:
    """Load JSON file with error handling."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {path}: {e}")


def save_json(path: Path, data: dict) -> None:
    """Save data to JSON file."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


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
        # Match id: value patterns, handling quotes and various formats
        # Matches: "id: value", "- id: value", "id: 'value'", "id: \"value\""
        pattern = r'(?:^|\n)\s*-?\s*id:\s*["\']?([^"\'\n\r]+)["\']?'
        for match in re.finditer(pattern, content):
            id_value = match.group(1).strip()
            if id_value and not id_value.startswith('#'):
                ids.add(id_value)
    except IOError:
        pass
    
    return ids


def get_automation_ids() -> set:
    """Get all automation IDs from YAML files and UI storage."""
    ids = set()
    
    # Check automation/ folder
    if AUTOMATION_PATH.exists():
        for f in AUTOMATION_PATH.glob("*.yaml"):
            ids.update(extract_ids_from_yaml_file(f))
    
    # Check automations.yaml in config root
    automations_yaml = CONFIG_PATH / "automations.yaml"
    ids.update(extract_ids_from_yaml_file(automations_yaml))
    
    # Check UI-based automations in .storage
    ui_automations = STORAGE_PATH / "automations"
    if ui_automations.exists():
        try:
            data = load_json(ui_automations)
            for item in data.get("data", {}).get("items", []):
                if item.get("id"):
                    ids.add(item["id"])
        except (FileNotFoundError, ValueError, KeyError):
            pass
    
    return ids


def get_script_ids() -> set:
    """Get all script IDs from YAML files and UI storage."""
    ids = set()
    
    # Check scripts/ folder
    if SCRIPT_PATH.exists():
        for f in SCRIPT_PATH.glob("*.yaml"):
            ids.update(extract_ids_from_yaml_file(f))
    
    # Check scripts.yaml in config root
    scripts_yaml = CONFIG_PATH / "scripts.yaml"
    ids.update(extract_ids_from_yaml_file(scripts_yaml))
    
    # Check UI-based scripts in .storage
    ui_scripts = STORAGE_PATH / "scripts"
    if ui_scripts.exists():
        try:
            data = load_json(ui_scripts)
            for item in data.get("data", {}).get("items", []):
                if item.get("id"):
                    ids.add(item["id"])
        except (FileNotFoundError, ValueError, KeyError):
            pass
    
    return ids


def get_scene_ids() -> set:
    """Get all scene IDs from YAML files and UI storage."""
    ids = set()
    
    # Check scenes/ folder
    if SCENE_PATH.exists():
        for f in SCENE_PATH.glob("*.yaml"):
            ids.update(extract_ids_from_yaml_file(f))
    
    # Check scenes.yaml in config root
    scenes_yaml = CONFIG_PATH / "scenes.yaml"
    ids.update(extract_ids_from_yaml_file(scenes_yaml))
    
    # Check UI-based scenes in .storage
    ui_scenes = STORAGE_PATH / "scenes"
    if ui_scenes.exists():
        try:
            data = load_json(ui_scenes)
            for item in data.get("data", {}).get("items", []):
                if item.get("id"):
                    ids.add(item["id"])
        except (FileNotFoundError, ValueError, KeyError):
            pass
    
    return ids



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
    
    # Build lookup sets
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
                    cur.execute("DELETE FROM states WHERE last_updated_ts < ?", (cutoff_ts,))
                    cur.execute("DELETE FROM events WHERE time_fired_ts < ?", (cutoff_ts,))
                    
                    # Clean orphaned attributes and event data
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
                    
                    conn.commit()
                    conn.execute("VACUUM")
                    log("✓ Database purged and vacuumed")
            else:
                log("✓ No old records to purge")
            
            return (states, events)
            
    except sqlite3.Error as e:
        log(f"⚠️  Database error: {e}")
        return (0, 0)


def cleanup_old_backups() -> int:
    """Remove backup files older than 7 days."""
    cutoff = (datetime.now() - timedelta(days=7)).timestamp()
    removed = 0
    
    for f in STORAGE_PATH.glob("*.backup.*"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    
    if removed:
        log(f"✓ Removed {removed} old backup files")
    else:
        log("✓ No old backup files to remove")
    
    return removed


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
    
    # Pattern for numeric suffix: _2, _3, _4, etc. (NOT _0 or _1)
    duplicate_suffix_pattern = re.compile(r'_([2-9]|\d{2,})$')
    
    candidates = []
    for entity in entities:
        entity_id = entity.get("entity_id", "")
        platform = entity.get("platform", "")
        
        # Check if entity_id ends with numeric suffix (_2, _3, etc.)
        match = duplicate_suffix_pattern.search(entity_id)
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
                for i in range(start, end + 1):
                    if 1 <= i <= max_num:
                        indices.add(i)
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
    print("\n" + "=" * 50)
    print("  Home Assistant Cleanup Tool")
    print("=" * 50)
    print(f"  Config: {CONFIG_PATH}")
    db_size = get_db_size()
    if db_size:
        print(f"  Database: {db_size:.1f} MB")
    print("=" * 50)
    print()
    print("  1. Full cleanup (all operations)")
    print("  2. Remove orphaned entities")
    print("  3. Clean deleted registry items")
    print("  4. Purge old database records")
    print("  5. Fix numeric suffix (_2, _3, etc.)")
    print("  6. Clean old backup files")
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
    time.sleep(5)
    
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
            print("\n" + "=" * 50)
            log("DRY RUN - Preview all changes")
            print("=" * 50 + "\n")
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
            time.sleep(5)
            
            try:
                fix_entity_suffix(dry_run=False)
            finally:
                log("Starting Home Assistant...")
                if method:
                    if not start_ha(method):
                        log("⚠️  Failed to start HA. Please start manually.")
                else:
                    log("Please start Home Assistant manually.")
            log("Done!")
        elif choice == '6':
            cleanup_old_backups()
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
