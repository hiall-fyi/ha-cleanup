#!/usr/bin/env python3
"""
Home Assistant Cleanup Tool
Interactive menu for various cleanup operations.

Features:
  - Remove orphaned entities (missing device/config/automation)
  - Fix _2 entity suffix issues
  - Clean deleted_entities and deleted_devices from registries
  - Purge old states/events and vacuum database
  - Auto-detects recorder purge_keep_days from HA config
  - Auto-detects config path (HAOS, Docker, Core)

Usage:
  python3 ha-cleanup.py              # Interactive menu
  python3 ha-cleanup.py --dry-run    # Preview all changes
"""
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

# Auto-detect config path
CONFIG_PATHS = ["/homeassistant", "/config", Path.home() / ".homeassistant"]
CONFIG_PATH = next((Path(p) for p in CONFIG_PATHS if Path(p).exists()), None)

if not CONFIG_PATH:
    print("Error: Could not find Home Assistant config directory")
    sys.exit(1)

ENTITY_REGISTRY = CONFIG_PATH / ".storage/core.entity_registry"
DEVICE_REGISTRY = CONFIG_PATH / ".storage/core.device_registry"
CONFIG_ENTRIES = CONFIG_PATH / ".storage/core.config_entries"
DB_PATH = CONFIG_PATH / "home-assistant_v2.db"
STORAGE_PATH = CONFIG_PATH / ".storage"
AUTOMATION_PATH = CONFIG_PATH / "automation"
DEFAULT_PURGE_DAYS = 14

# Patterns for _2 suffix fix
SUFFIX_PATTERNS = [
    ("_2", ["template", "tado_ce"]),
]

# ============================================================
# Utility Functions
# ============================================================

def log(msg):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}")

def backup_file(path):
    backup = f"{path}.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(path, backup)
    return backup

def load_json(path):
    with open(path) as f:
        return json.load(f)

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def get_db_size():
    return DB_PATH.stat().st_size / (1024 * 1024) if DB_PATH.exists() else 0

def stop_ha():
    for cmd in [["ha", "core", "stop"], ["systemctl", "stop", "home-assistant@homeassistant"], ["docker", "stop", "homeassistant"]]:
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return cmd[0]
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    return None

def start_ha(method):
    cmds = {"ha": ["ha", "core", "start"], "systemctl": ["systemctl", "start", "home-assistant@homeassistant"], "docker": ["docker", "start", "homeassistant"]}
    if method in cmds:
        subprocess.run(cmds[method], check=True)

def get_recorder_purge_days():
    """Get purge_keep_days from HA recorder config, fallback to default."""
    config_yaml = CONFIG_PATH / "configuration.yaml"
    if config_yaml.exists():
        try:
            in_recorder = False
            for line in open(config_yaml):
                stripped = line.strip()
                if stripped.startswith("recorder:"):
                    in_recorder = True
                    continue
                if in_recorder and stripped and not stripped.startswith("#") and not stripped.startswith("-") and not line.startswith(" ") and not line.startswith("\t"):
                    in_recorder = False
                if in_recorder and "purge_keep_days:" in stripped:
                    value = stripped.split(":", 1)[1].strip()
                    return int(value)
        except (ValueError, IOError):
            pass
    
    if CONFIG_ENTRIES.exists():
        try:
            data = load_json(CONFIG_ENTRIES)
            for entry in data.get("data", {}).get("entries", []):
                if entry.get("domain") == "recorder":
                    options = entry.get("options", {})
                    if "purge_keep_days" in options:
                        return options["purge_keep_days"]
        except (json.JSONDecodeError, KeyError):
            pass
    
    return DEFAULT_PURGE_DAYS


# ============================================================
# Cleanup Functions
# ============================================================

def get_automation_ids():
    """Get all automation IDs from both YAML files and UI storage."""
    ids = set()
    
    if AUTOMATION_PATH.exists():
        for f in AUTOMATION_PATH.glob("*.yaml"):
            for line in open(f):
                if line.strip().startswith("- id:") or line.strip().startswith("id:"):
                    ids.add(line.split(":", 1)[1].strip().strip("'\""))
    
    automations_yaml = CONFIG_PATH / "automations.yaml"
    if automations_yaml.exists():
        for line in open(automations_yaml):
            if line.strip().startswith("- id:") or line.strip().startswith("id:"):
                ids.add(line.split(":", 1)[1].strip().strip("'\""))
    
    ui_automations = STORAGE_PATH / "automations"
    if ui_automations.exists():
        try:
            data = load_json(ui_automations)
            for item in data.get("data", {}).get("items", []):
                if item.get("id"):
                    ids.add(item["id"])
        except (json.JSONDecodeError, KeyError):
            pass
    
    return ids

def find_orphaned_entities():
    entity_data = load_json(ENTITY_REGISTRY)
    devices = {d["id"] for d in load_json(DEVICE_REGISTRY)["data"]["devices"]}
    config_entries = {e["entry_id"] for e in load_json(CONFIG_ENTRIES)["data"]["entries"]}
    automation_ids = get_automation_ids()

    orphans = []
    for e in entity_data['data']['entities']:
        did, cid = e.get("device_id"), e.get("config_entry_id")
        is_orphan = (did and did not in devices) or (cid and cid not in config_entries)
        
        if e.get('platform') == 'automation':
            unique_id = e.get('unique_id')
            if unique_id and unique_id not in automation_ids:
                is_orphan = True
            else:
                is_orphan = False
        
        if is_orphan:
            orphans.append((e['platform'], e['entity_id'], e.get('original_name', '')))
    return orphans

def cleanup_orphaned_entities(dry_run=False):
    orphans = find_orphaned_entities()
    if not orphans:
        log("✓ No orphaned entities found")
        return 0
    if dry_run:
        log(f"Found {len(orphans)} orphaned entities:")
        for platform, eid, name in sorted(orphans):
            log(f"  - {platform}: {eid} ({name})")
        return len(orphans)

    backup_file(ENTITY_REGISTRY)
    orphan_eids = {o[1] for o in orphans}
    data = load_json(ENTITY_REGISTRY)
    data['data']['entities'] = [e for e in data['data']['entities'] if e['entity_id'] not in orphan_eids]
    save_json(ENTITY_REGISTRY, data)
    log(f"✓ Removed {len(orphans)} orphaned entities")
    return len(orphans)

def cleanup_deleted_items(dry_run=False):
    count = 0
    for path, key in [(ENTITY_REGISTRY, "deleted_entities"), (DEVICE_REGISTRY, "deleted_devices")]:
        data = load_json(path)
        n = len(data['data'].get(key, []))
        if n:
            if not dry_run:
                backup_file(path)
                data['data'][key] = []
                save_json(path, data)
            log(f"{'Would clean' if dry_run else '✓ Cleaned'} {n} {key.replace('_', ' ')}")
            count += n
    return count

def purge_database(dry_run=False):
    if not DB_PATH.exists():
        log("✓ No database found, skipping")
        return 0, 0
    purge_days = get_recorder_purge_days()
    log(f"Using purge_keep_days: {purge_days}")
    cutoff_ts = int((datetime.now() - timedelta(days=purge_days)).timestamp())
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM states WHERE last_updated_ts < ?", (cutoff_ts,))
    states = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM events WHERE time_fired_ts < ?", (cutoff_ts,))
    events = cur.fetchone()[0]

    if states or events:
        log(f"{'Would purge' if dry_run else 'Purging'} {states} states, {events} events older than {purge_days} days")
        if not dry_run:
            cur.execute("DELETE FROM states WHERE last_updated_ts < ?", (cutoff_ts,))
            cur.execute("DELETE FROM events WHERE time_fired_ts < ?", (cutoff_ts,))
            cur.execute("DELETE FROM state_attributes WHERE NOT EXISTS (SELECT 1 FROM states WHERE states.attributes_id = state_attributes.attributes_id)")
            cur.execute("DELETE FROM event_data WHERE NOT EXISTS (SELECT 1 FROM events WHERE events.data_id = event_data.data_id)")
            conn.commit()
            conn.execute("VACUUM")
            log("✓ Database purged and vacuumed")
    else:
        log("✓ No old records to purge")
    conn.close()
    return states, events

def cleanup_old_backups():
    cutoff = (datetime.now() - timedelta(days=7)).timestamp()
    removed = 0
    for f in STORAGE_PATH.glob("*.backup.*"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    if removed:
        log(f"✓ Removed {removed} old backup files")
    return removed

def find_suffix_entities():
    """Find entities with _2 suffix that can be fixed."""
    data = load_json(ENTITY_REGISTRY)
    fixes = []
    
    for entity in data["data"]["entities"]:
        entity_id = entity.get("entity_id", "")
        platform = entity.get("platform", "")
        
        for suffix, platforms in SUFFIX_PATTERNS:
            if suffix in entity_id and platform in platforms:
                old_id = entity_id
                new_id = entity_id.replace(suffix, "")
                
                existing = [e for e in data["data"]["entities"] if e.get("entity_id") == new_id]
                if existing:
                    continue
                
                fixes.append((old_id, new_id, platform))
                break
    
    return fixes

def fix_entity_suffix(dry_run=False):
    """Fix _2 suffix in entity registry."""
    fixes = find_suffix_entities()
    
    if not fixes:
        log("✓ No _2 suffix entities to fix")
        return 0
    
    if dry_run:
        log(f"Found {len(fixes)} entities with _2 suffix:")
        for old_id, new_id, platform in fixes:
            log(f"  - {old_id} -> {new_id} ({platform})")
        return len(fixes)
    
    backup_file(ENTITY_REGISTRY)
    data = load_json(ENTITY_REGISTRY)
    
    fix_map = {old: new for old, new, _ in fixes}
    for entity in data["data"]["entities"]:
        if entity.get("entity_id") in fix_map:
            entity["entity_id"] = fix_map[entity["entity_id"]]
    
    save_json(ENTITY_REGISTRY, data)
    log(f"✓ Fixed {len(fixes)} entity suffixes")
    return len(fixes)


# ============================================================
# Menu System
# ============================================================

def print_menu():
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
    print("  5. Fix _2 entity suffix")
    print("  6. Clean old backup files")
    print()
    print("  d. Dry run (preview all)")
    print("  q. Quit")
    print()

def confirm_action(msg):
    response = input(f"⚠️  {msg} [y/N]: ")
    return response.lower() == 'y'

def run_with_ha_restart(operations, dry_run=False):
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
        log("Warning: Could not stop HA automatically.")
        if not confirm_action("Please stop HA manually. Continue when stopped?"):
            return
    time.sleep(5)
    
    db_before = get_db_size()
    
    try:
        for op in operations:
            op(dry_run=False)
        cleanup_old_backups()
        
        db_after = get_db_size()
        if db_before and db_after:
            saved = db_before - db_after
            if saved > 0:
                log(f"Database: {db_before:.1f} MB → {db_after:.1f} MB ({saved:.1f} MB saved)")
    finally:
        log("Starting Home Assistant...")
        if method:
            start_ha(method)
        else:
            log("Please start Home Assistant manually.")
    
    log("Done!")

def interactive_menu():
    while True:
        print_menu()
        choice = input("  Select option: ").strip().lower()
        
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
            run_with_ha_restart([
                cleanup_orphaned_entities,
                cleanup_deleted_items,
                purge_database,
                fix_entity_suffix,
            ])
        elif choice == '2':
            run_with_ha_restart([cleanup_orphaned_entities])
        elif choice == '3':
            run_with_ha_restart([cleanup_deleted_items])
        elif choice == '4':
            run_with_ha_restart([purge_database])
        elif choice == '5':
            run_with_ha_restart([fix_entity_suffix])
        elif choice == '6':
            cleanup_old_backups()
        else:
            print("Invalid option, try again.")

# ============================================================
# Main
# ============================================================

if __name__ == "__main__":
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
