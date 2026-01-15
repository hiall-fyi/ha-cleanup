#!/usr/bin/env python3
"""
Home Assistant Cleanup Script
Removes orphaned entities, cleans registries, purges old database records.

Usage:
  python3 ha-cleanup.py --dry-run    # Preview changes
  python3 ha-cleanup.py              # Execute cleanup (requires HA restart)
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
PURGE_DAYS = 14

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

def get_yaml_automation_ids():
    ids = set()
    if not AUTOMATION_PATH.exists():
        return ids
    for f in AUTOMATION_PATH.glob("*.yaml"):
        for line in open(f):
            if line.strip().startswith("- id:"):
                ids.add(line.split(":", 1)[1].strip().strip("'\""))
    return ids

def find_orphaned_entities():
    entity_data = load_json(ENTITY_REGISTRY)
    devices = {d["id"] for d in load_json(DEVICE_REGISTRY)["data"]["devices"]}
    config_entries = {e["entry_id"] for e in load_json(CONFIG_ENTRIES)["data"]["entries"]}
    yaml_automations = get_yaml_automation_ids()

    orphans = []
    for e in entity_data['data']['entities']:
        did, cid = e.get("device_id"), e.get("config_entry_id")
        is_orphan = (did and did not in devices) or (cid and cid not in config_entries)
        if e.get('platform') == 'automation' and e.get('unique_id') not in yaml_automations:
            is_orphan = True
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
        return
    cutoff_ts = int((datetime.now() - timedelta(days=PURGE_DAYS)).timestamp())
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM states WHERE last_updated_ts < ?", (cutoff_ts,))
    states = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM events WHERE time_fired_ts < ?", (cutoff_ts,))
    events = cur.fetchone()[0]

    if states or events:
        log(f"{'Would purge' if dry_run else 'Purging'} {states} states, {events} events older than {PURGE_DAYS} days")
        if not dry_run:
            cur.execute("DELETE FROM states WHERE last_updated_ts < ?", (cutoff_ts,))
            cur.execute("DELETE FROM events WHERE time_fired_ts < ?", (cutoff_ts,))
            cur.execute("DELETE FROM state_attributes WHERE NOT EXISTS (SELECT 1 FROM states WHERE states.attributes_id = state_attributes.attributes_id)")
            cur.execute("DELETE FROM event_data WHERE NOT EXISTS (SELECT 1 FROM events WHERE events.data_id = event_data.data_id)")
            conn.commit()
            conn.execute("VACUUM")
    conn.close()
    if not dry_run:
        log("✓ Database purged and vacuumed")

def cleanup_old_backups():
    cutoff = (datetime.now() - timedelta(days=7)).timestamp()
    removed = 0
    for f in STORAGE_PATH.glob("*.backup.*"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    if removed:
        log(f"✓ Removed {removed} old backup files")

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

if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv

    log("=" * 50)
    log(f"Home Assistant Cleanup {'(DRY RUN)' if dry_run else ''}")
    log("=" * 50)
    log(f"Config path: {CONFIG_PATH}")

    db_before = get_db_size()
    if db_before:
        log(f"Database size: {db_before:.1f} MB\n")

    if not dry_run:
        log("Stopping Home Assistant...")
        method = stop_ha()
        if not method:
            log("Warning: Could not stop HA automatically. Please stop it manually.")
            input("Press Enter when HA is stopped...")
        time.sleep(10)

    try:
        orphans = cleanup_orphaned_entities(dry_run)
        deleted = cleanup_deleted_items(dry_run)
        purge_database(dry_run)
        if not dry_run:
            cleanup_old_backups()

        db_after = get_db_size()
        log("\n" + "=" * 50)
        log("Summary:")
        log(f"  Orphaned entities: {orphans}")
        log(f"  Deleted registry items: {deleted}")
        if db_before and not dry_run:
            log(f"  Database: {db_before:.1f} MB → {db_after:.1f} MB ({db_before - db_after:.1f} MB saved)")
        log("=" * 50)
    finally:
        if not dry_run:
            log("\nStarting Home Assistant...")
            if method:
                start_ha(method)
            else:
                log("Please start Home Assistant manually.")
    log("Done!")
