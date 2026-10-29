# HA Cleanup Features Guide

The full reference for every option, the restore menu, unattended and remote runs, and what each operation touches. For installing and a first run, start with the [README](README.md).

- [Usage details](#usage-details)
- [Restore from Backup](#restore-from-backup)
- [Detailed Feature Guide](#detailed-feature-guide)
- [Verification record](#verification-record)

---

## Usage details

### Scheduled / Non-Interactive Runs

Options 1 to 6 can run without the menu. `--run=<option>` picks one and
`--yes` skips the confirmation prompt:

```bash
python3 ha-cleanup.py --run=3 --yes
```

```
[2026-09-04 05:58:03] Stopping Home Assistant...
[2026-09-04 05:58:12] ✓ Cleaned 143 deleted entities
[2026-09-04 05:58:12] ✓ Cleaned 1 deleted devices
[2026-09-04 05:58:12] ✓ No old backup files to remove (found 2 backups, all within 7 days)
[2026-09-04 05:58:12] Database: 5226.9 MB → 5224.4 MB (2.5 MB saved)
[2026-09-04 05:58:12] Starting Home Assistant...
[2026-09-04 05:58:22] Done!
```

This is the flag combination for a cron job or systemd timer: nothing
prompts, and the process exits `0` on success or non-zero if anything
failed, so cron's own failure notification (mail, `OnFailure=`, a
healthcheck ping) picks it up. Options 7 and 8 need you to pick specific
entities or a specific backup, so they're rejected with an explanation
rather than run unattended:

```
$ python3 ha-cleanup.py --run=7 --yes
[2026-08-22 12:36:27] Option 7 requires interactive selection and can't be automated.
$ echo $?
2
```

`--dry-run` combines with `--run` to preview a single option instead of
everything:

```bash
python3 ha-cleanup.py --run=3 --dry-run
```

```
[2026-08-22 12:36:27] Would clean 49 deleted entities
[2026-08-22 12:36:27] Would clean 4 deleted devices
```

**Cron**, once a week at 4am:

```cron
0 4 * * 0 cd /path/to/config && python3 ha-cleanup.py --run=3 --yes >> /var/log/ha-cleanup.log 2>&1
```

**Options 1 to 5 need to stop Home Assistant, so they need to run from
somewhere that actually can stop it**: a host-level cron job or systemd
timer, as above, or a scheduler add-on that runs outside HA's own container
(the SSH & Terminal add-on's own cron, for example). Home Assistant's
`shell_command:` runs *inside* HA Core's own container, and that container
has none of `ha`, `systemctl` or `docker` available to it. Every way this
tool tries to stop HA fails from in there, so options 1 to 5 triggered
this way always abort with "Could not stop HA automatically", whatever you
pass on the command line.

**Option 6 doesn't stop HA at all**, so it's the one that's actually safe to
trigger from `shell_command:`:

```yaml
shell_command:
  ha_cleanup_old_backups: "python3 /path/to/ha-cleanup.py --run=6 --yes"
```

```yaml
automation:
  - alias: "Weekly Backup Cleanup"
    trigger:
      - platform: time
        at: "04:00:00"
    condition:
      - condition: time
        weekday:
          - sun
    action:
      - action: shell_command.ha_cleanup_old_backups
        response_variable: cleanup_result
      - if: "{{ cleanup_result['returncode'] != 0 }}"
        then:
          - action: notify.persistent_notification
            data:
              message: >-
                ha-cleanup failed (exit {{ cleanup_result['returncode'] }}):
                {{ cleanup_result['stderr'] }}
```

`response_variable` is what makes the exit code visible to HA at all. Without
it, `shell_command:` is fire-and-forget and a failed run just quietly doesn't
happen. `returncode` is `0` for success, `1` if the option itself failed, `2`
if `--run` was pointed at an option that needs interactive selection.

### Running From a Separate Host (Unraid, Proxmox, etc.)

If Home Assistant itself runs inside a VM or container managed by something
else, the scheduler usually lives on that host rather than alongside HA, and
has to reach in over SSH. Two things trip this up:

**The remote command needs its own login shell.** A bare
`ssh user@host "python3 /config/ha-cleanup.py --run=3 --yes"` can fail to
find `python3`, even though the identical command works fine once you're
logged in interactively. Wrap it in `bash -lc`, with the inner command
single-quoted:

```bash
ssh -p 22 hassio@192.168.0.12 "bash -lc 'python3 /config/ha-cleanup.py --run=3 --yes'"
```

**A scheduler that runs each line of a script as its own step can lose
shell variables between lines.** Unraid's User Scripts plugin does this: set
a variable on one line and it's gone by the time the `ssh` line runs.
Wrapping the whole script in `( ... )` keeps it running as one block:

```bash
#!/bin/bash
(
  HA_HOST="192.168.0.12"
  HA_PORT="22"
  ssh -p "$HA_PORT" -o StrictHostKeyChecking=no "hassio@${HA_HOST}" \
    "bash -lc 'python3 /config/ha-cleanup.py --run=3 --yes'"
)
```

To update `ha-cleanup.py` itself before running it, use a separate `ssh`
call for the download and another for `chmod`. Chaining `wget` and `chmod`
onto one line didn't work reliably:

```bash
ssh -p "$HA_PORT" -o StrictHostKeyChecking=no "hassio@${HA_HOST}" \
  "wget -O /config/ha-cleanup.py https://raw.githubusercontent.com/hiall-fyi/ha-cleanup/main/ha-cleanup.py"
ssh -p "$HA_PORT" -o StrictHostKeyChecking=no "hassio@${HA_HOST}" \
  "chmod +x /config/ha-cleanup.py"
```

### Numeric Suffix Fix (Interactive)

When you select option 7, you'll see an interactive selection:

```
Found 12 entities with numeric suffix:
======================================================================
⚠️  WARNING: Not all suffixes are duplicates!
   Some are legitimate (e.g., button_4, sim_2, pm2_5)
   Review carefully before selecting.
======================================================================

  [ 1] device_tracker.cronus_clients_pixel_6
       -> device_tracker.cronus_clients_pixel (mikrotik_ce)
  [ 2] sensor.met_office_pm2_5
       -> sensor.met_office_pm2 (atmos_ce)
  [ 3] button.cronus_wake_pixel_6
       -> button.cronus_wake_pixel (mikrotik_ce)
  ...

Enter selection:
  - Numbers: 1,3,5 or 1-5 or 1,3-5,8
  - 'all' to fix all (DANGEROUS!)
  - 'none' or Enter to skip

Selection: 1
```

This lets you manually review and pick only the entities that are actually duplicates.

**Collision protection:** If two entities would both rename to the same target (e.g. both `sensor.x_2` and `sensor.x_3` with no existing `sensor.x`), the tool automatically excludes both from the list to prevent registry corruption.

**What isn't offered:** entities ending in a number Home Assistant could never have generated. Its numbering counts up from `_2`, so anything past `_99` (or a model number like `sensor.inverter_2400`) is skipped, as is any run with a `_1` sibling, which means the device did the numbering. Network integrations are the other big source of noise, so a tail that continues a MAC address (`..._01_da_12`) or a port number after `tcp` / `udp` (`..._dns_udp_53`) is skipped too. On the author's own 2223-entity setup, measured on 2026-08-01, these filters took the list from 45 candidates down to 8. Genuine suffixes that look identical to duplicates, such as `button_4` or `pm2_5`, are still listed, which is why selection stays manual.

---


## Restore from Backup

Restore brings back entities you deleted by accident, from the backup files this tool writes before it changes a registry.

### Restore Menu

Select option **8** from the main menu to access the restore submenu:

```
======================================================================
  Restore from Backup
======================================================================

  1. List available backups
  2. Preview backup differences
  3. Selective restore entities
  4. Full restore registry

  d. Toggle dry-run (currently OFF)
  r. Refresh backup list
  b. Back to main menu
```

### Restore Options

#### 1. List Available Backups

Shows all backup files with timestamps, type, record count (entities or devices), and file size:

```
Found 6 backup files:
======================================================================
#    Timestamp            Type               Entities   Size (MB)
------------------------------------------------------------
1    2026-04-03 11:09:11  entity_registry    1677       1.50
2    2026-04-03 11:09:11  device_registry    142        0.12
3    2026-04-01 21:17:00  entity_registry    1711       1.58
...
```

#### 2. Preview Backup Differences

Compare a backup with your current registry to see what changed:

```
Backup: core.entity_registry.backup.20260403_110911
Timestamp: 2026-04-03 11:09:11
Entities in backup: 1677

======================================================================
DELETED ENTITIES (in backup but not in current): 3
======================================================================
  1. sensor.living_room_temperature (mqtt)
     Name: Living Room Temperature
  2. light.bedroom_lamp (hue)
  3. switch.garage_door (homeassistant)

======================================================================
NEW ENTITIES (in current but not in backup): 1
======================================================================
  1. sensor.new_sensor (homeassistant)

======================================================================
MODIFIED ENTITIES: 2
======================================================================
  1. sensor.test
     disabled_by: None → user
```

#### 3. Selective Restore Entities

Restore only specific entities from a backup:

1. Select a backup file
2. View deleted entities (entities in backup but not in current)
3. Select which entities to restore using the same syntax as suffix fix:
   - Numbers: `1,3,5` or `1-5` or `1,3-5,8`
   - `all` to restore all deleted entities
   - `none` or Enter to skip
4. Confirm selection
5. Script automatically stops HA, restores entities, and starts HA

**Example:**

```
Found 3 deleted entities:
======================================================================
  [ 1] sensor.living_room_temperature (mqtt)
       Name: Living Room Temperature
  [ 2] light.bedroom_lamp (hue)
  [ 3] switch.garage_door (homeassistant)

Enter selection:
  - Numbers: 1,3,5 or 1-5 or 1,3-5,8
  - 'all' to restore all
  - 'none' or Enter to skip

Selection: 1,3

Will restore 2 entities:
  - sensor.living_room_temperature (mqtt)
  - switch.garage_door (homeassistant)

⚠️  Restore these 2 entities? [y/N]: y
```

#### 4. Full Restore Registry

Completely restore the entire registry from a backup:

```
Backup: core.entity_registry.backup.20260403_110911
Timestamp: 2026-04-03 11:09:11
Entities in backup: 1677
Entities in current: 1680
Difference: -3

⚠️  Fully restore registry from this backup? [y/N]: y
```

**Warning:** This replaces your entire entity registry. Use with caution!

### When to Use Restore

- **Accidentally deleted entities**: Use selective restore to bring back specific entities
- **Integration removal gone wrong**: Preview differences to see what was lost
- **Testing rollback**: Full restore to revert to a previous state
- **Entity corruption**: Restore from a known-good backup

### Safety Features

- **Auto-backup before restore**: Current registry is backed up before any restore operation
- **Preview before restore**: See exactly what will change
- **Interactive selection**: Choose specific entities to restore
- **Confirmation prompts**: Asks before making changes

---

## Detailed Feature Guide

### Option 1: Full Cleanup

Runs options 2, 3, 4 and 6 in one go. It leaves out the suffix fix (option 7), which needs you to pick entities, and the statistics cleanup (option 5), which you run on its own.

**What it does:**
1. Removes orphaned entities
2. Cleans deleted registry items
3. Purges old database records

It then cleans old backup files (7+ days) before starting Home Assistant again.

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-08-01 14:30:13] Stopping Home Assistant...
[2026-08-01 14:30:22] ✓ No orphaned entities found
[2026-08-01 14:30:22] ✓ Cleaned 89 deleted entities
[2026-08-01 14:30:22] ✓ Cleaned 1 deleted devices
[2026-08-01 14:30:22] Using purge_keep_days: 14 (from default)
[2026-08-01 14:30:22]   [Count] Starting...
[2026-08-01 14:30:23]   [Count] Done in 0.3s (8,085,627 states, 77,573 events)
[2026-08-01 14:30:23] Purging 8,085,627 states, 77,573 events older than 14 days
[2026-08-01 14:30:23]   [States] Starting...
[2026-08-01 14:31:09]     Unlinked 8,029,055 old_state_id references
[2026-08-01 14:31:10]     Batch 1/81: deleted 100,000/8,085,627 (1%)
...
[2026-08-01 14:33:51]   [States] Done in 208.6s (deleted 8,085,627 rows)
[2026-08-01 14:33:52]   [Events] Done in 0.9s (deleted 77,573 rows)
[2026-08-01 14:46:19]   [Orphan Attributes] Done in 746.9s (deleted 3,205,456 rows)
[2026-08-01 14:46:19]   [Orphan Event Data] Done in 0.0s (deleted 568 rows)
[2026-08-01 14:46:19]   [VACUUM] Starting...
[2026-08-01 14:47:09]   [VACUUM] Done in 49.3s (DB: 5920.3 → 2748.5 MB, 3171.8 MB saved)
[2026-08-01 14:47:09] ✓ Database purged
[2026-08-01 14:47:09] ✓ Removed 6 old backup files (older than 7 days)
[2026-08-01 14:47:09] Database: 5924.4 MB → 2748.5 MB (3175.9 MB saved)
[2026-08-01 14:47:09] Starting Home Assistant...
[2026-08-01 14:47:24] Done!

⚠️  Suffix fix requires manual selection. Run option 7 separately.
```

**When to use:**
- Regular maintenance (monthly recommended)
- After removing multiple integrations
- When database is getting large

---

### Option 2: Remove Orphaned Entities

Removes entities that reference deleted devices, config entries, or definitions.

**How it works:**

1. Scans entity registry for broken references
2. Checks if device_id exists in device registry
3. Checks if config_entry_id exists in config entries
4. For automations/scripts/scenes, checks if ID exists in YAML or UI storage
5. Removes entities with missing references

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-08-22 12:46:23] Stopping Home Assistant...
[2026-08-22 12:46:32] ✓ No orphaned entities found
[2026-08-22 12:46:32] ✓ No old backup files to remove (found 2 backups, all within 7 days)
[2026-08-22 12:46:32] Starting Home Assistant...
[2026-08-22 12:46:47] Done!
```

**When to use:**
- After removing integrations
- After deleting devices
- When you see "unavailable" entities that won't go away
- After cleaning up automations/scripts/scenes

**Safety:**
- Backs up entity registry before removal
- Only removes entities with confirmed broken references
- Does NOT remove entities if unique_id cannot be verified

---

### Option 3: Clean Deleted Registry Items

Clears the "soft-deleted" items from entity and device registries.

**What are deleted registry items?**

When you delete an entity or device in HA, it's not immediately removed from the registry files. Instead, it's moved to a `deleted_entities` or `deleted_devices` list. This allows HA to track what was deleted and prevent ID conflicts.

Over time, these lists can grow large and are safe to clean.

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-08-22 12:38:01] Stopping Home Assistant...
[2026-08-22 12:38:10] ✓ Cleaned 49 deleted entities
[2026-08-22 12:38:10] ✓ Cleaned 4 deleted devices
[2026-08-22 12:38:10] ✓ Removed 2 old backup files (older than 7 days)
[2026-08-22 12:38:10] Starting Home Assistant...
[2026-08-22 12:38:21] Done!
```

**When to use:**
- After deleting many entities/devices
- Regular maintenance (quarterly)
- When registry files are getting large

**Files affected:**
- `.storage/core.entity_registry` (deleted_entities list)
- `.storage/core.device_registry` (deleted_devices list)

---

### Option 4: Purge Old Database Records

Removes old states and events from the database based on your recorder configuration.

**How it works:**

1. Reads `purge_keep_days` from your recorder config and logs where it found it (default: 14 days)
2. Tunes SQLite settings (cache size, memory-mapped I/O) for faster deletes
3. Counts purgeable states and events
4. Clears the links old state rows hold to each other, so removing them doesn't leave broken internal references
5. Batch deletes states older than X days (adaptive batch size with progress)
6. Batch deletes events older than X days
7. Cleans orphaned state_attributes using optimised LEFT JOIN queries
8. Cleans orphaned event_data the same way
9. Restores the SQLite settings from step 2, folds the write-ahead log back into the database, and puts the journal mode back to whatever your database started in
10. Checks disk space, then runs VACUUM to reclaim space (skips if not enough room). Because step 9 already folded the log back in, the size it reports is the size on your disk

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-08-22 12:46:55] Stopping Home Assistant...
[2026-08-22 12:47:04] Using purge_keep_days: 14 (from default)
[2026-08-22 12:47:04]   [Count] Starting...
[2026-08-22 12:47:04]   [Count] Done in 0.3s (8,401,505 states, 101,796 events)
[2026-08-22 12:47:04] Purging 8,401,505 states, 101,796 events older than 14 days
[2026-08-22 12:47:04]   [States] Starting...
[2026-08-22 12:47:38]     Unlinked 8,293,904 old_state_id references
[2026-08-22 12:47:39]     Batch 1/85: deleted 100,000/8,401,505 (1%)
...
[2026-08-22 12:49:34]     Batch 85/85: deleted 8,401,505/8,401,505 (100%)
[2026-08-22 12:49:34]   [States] Done in 149.9s (deleted 8,401,505 rows)
[2026-08-22 12:49:34]   [Events] Starting...
[2026-08-22 12:49:35]   [Events] Done in 0.7s (deleted 101,796 rows)
[2026-08-22 12:49:35]   [Orphan Attributes] Starting...
[2026-08-22 12:49:35]     Counting orphans...
[2026-08-22 12:49:43]     Found 3,018,013 orphan rows
[2026-08-22 12:59:35]   [Orphan Attributes] Done in 600.1s (deleted 3,018,013 rows)
[2026-08-22 12:59:35]   [Orphan Event Data] Starting...
[2026-08-22 12:59:35]     Counting orphans...
[2026-08-22 12:59:35]     Found 995 orphan rows
[2026-08-22 12:59:35]   [Orphan Event Data] Done in 0.0s (deleted 995 rows)
[2026-08-22 12:59:35]   [VACUUM] Starting...
[2026-08-22 12:59:35]     DB size before: 5927.2 MB
[2026-08-22 13:00:38]   [VACUUM] Done in 63.3s (DB: 5927.2 → 2839.9 MB, 3087.3 MB saved)
[2026-08-22 13:00:38] ✓ Database purged
[2026-08-22 13:00:38] Database: 5938.5 MB → 2839.9 MB (3098.6 MB saved)
[2026-08-22 13:00:38] Starting Home Assistant...
[2026-08-22 13:00:55] Done!
```

**When to use:**
- Database file is getting too large
- Running low on disk space
- Want to speed up database queries
- Regular maintenance (monthly)

**Where purge_keep_days is read from** (checked in this order):

1. `configuration.yaml`:
   ```yaml
   recorder:
     purge_keep_days: 14
   ```

2. `packages/*.yaml`, if you split your config with `packages: !include_dir_named packages/` and put `recorder:` in there

3. Recorder integration options in `.storage/core.config_entries`

4. Default: 14 days if not configured

The log line tells you which one was used, e.g. `Using purge_keep_days: 14 (from packages/*.yaml)`. If it says `(from default)` and you expected it to find your setting, that's your cue to check where `recorder:` actually lives.

**Warning:** This permanently deletes historical data. Make sure your `purge_keep_days` setting is correct before running.

---

### Option 5: Remove Orphaned Long-Term Statistics

Removes long-term statistics for entities that no longer exist in the registry.

**Why does this happen?**

Home Assistant keeps long-term statistics in the database independently of the entity registry. Deleting an entity, or removing the integration that provided it, doesn't touch its old `statistics_meta` row or the hourly/5-minute data linked to it. The numbers just sit there under an entity ID nothing points to any more. I'm not aware of a Home Assistant screen that lists them; a diagnostics add-on like Spook is usually how people first notice they exist.

**How it works:**

1. Reads every `statistics_meta` row where `source = 'recorder'`, the ones keyed by a real entity_id
2. Checks each row's `statistic_id` against the current entity registry
3. For anything absent from the registry, also checks whether it's still writing new statistics within the last 7 days. A YAML `template:`, `mqtt:`, `command_line`, or `sql` sensor with `state_class` set but no `unique_id` is live but never appears in the registry, so without this check it would look identical to a genuinely deleted entity
4. For anything both absent from the registry and with no recent statistics, deletes its rows from `statistics` and `statistics_short_term` first, then the `statistics_meta` row itself
5. Logs the total number of orphaned statistics removed

**What it leaves alone:**

Statistics with any `source` other than `recorder` (utility meter helpers, energy-dashboard cost sensors, and other externally-computed statistics) use a different `statistic_id` shape and are never evaluated against the registry. They're left exactly as they are, whether or not the entity behind them still exists.

Entities absent from the registry but still writing new statistics. A YAML `template:`, `mqtt:`, `command_line`, or `sql` sensor with `state_class` set but no `unique_id` never gets a registry entry, even though it's live and still recording data. As long as its `statistics` table has a row newer than 7 days, it's treated as live and left alone.

**A note on timing:**

If a diagnostics tool like Spook already lists something as an orphaned statistic, this option might not remove it straight away. It's most likely still inside that 7-day window. Spook flags a statistic the moment its entity is gone; this tool waits until the data itself has gone quiet too, as the safety margin described above. Run it again in a few days and it'll catch up.

**Example output:**

```
⚠️  This will stop Home Assistant. Continue? [y/N]: y
[2026-09-01 06:50:36] Stopping Home Assistant...
[2026-09-01 06:50:46]   [Orphan statistics] Starting...
[2026-09-01 06:50:46]     Batch 1/1: deleted 44/44 (100%)
[2026-09-01 06:50:46]   [Orphan statistics] Done in 0.0s (deleted 44 rows)
[2026-09-01 06:50:46]   [Orphan statistics_short_term] Starting...
[2026-09-01 06:50:46]   [Orphan statistics_short_term] Done in 0.0s (deleted 0 rows)
[2026-09-01 06:50:46] ✓ Removed 4 orphaned statistics
[2026-09-01 06:50:46] ✓ Removed 2 old backup files (older than 7 days)
[2026-09-01 06:50:46] Database: 4684.3 MB → 4678.8 MB (5.5 MB saved)
[2026-09-01 06:50:46] Starting Home Assistant...
[2026-09-01 06:51:01] Done!
```

`statistics_short_term` only holds a rolling few days, so it's common for it to have nothing left to delete by the time an entity's been gone long enough to show up here. That's what the zero above is.

**When to use:**
- After removing an integration that had months or years of history: its graphs are gone from the UI, but the numbers are still in the database
- Alongside regular database maintenance (option 4): the purge only touches `states`/`events`, this is the same idea for long-term statistics
- Before or after running a diagnostics add-on like Spook, if you want the statistics side of things already clean

---

### Option 6: Clean Old Backup Files

Removes backup files older than 7 days.

**What are backup files?**

Before it changes a registry file, the script copies it to a timestamped backup. Options 1, 2, 3 and 7 and both restore options do this, for example:
- `core.entity_registry.backup.20260403_110911`
- `core.device_registry.backup.20260403_110911` (option 3 backs up the device registry as well when it has deleted devices to clean)

These accumulate over time and can be safely deleted after 7 days.

**Example output:**

```
✓ Removed 5 old backup files
```

or

```
✓ No old backup files to remove
```

**When to use:**
- Regular maintenance (monthly)
- Running low on disk space
- After multiple cleanup operations

**Note:** This does NOT require HA restart and runs immediately.

**Files cleaned:**
- `.storage/*.backup.*` files older than 7 days

---

### Option 7: Fix Numeric Suffix

Interactively fix entity IDs with `_2`, `_3`, etc. suffixes.

**Why does this happen?**

When you remove and re-add an integration, HA sometimes appends a numeric suffix to prevent ID conflicts:
- `sensor.living_room_temperature` becomes `sensor.living_room_temperature_2`

This happens because the old entity ID is still in the "deleted_entities" list.

**How it works:**

1. Scans entity registry for entities ending in `_2` through `_99`, the range Home Assistant's own numbering produces (it counts up from 2, so a longer number like `sensor.solar_5000` was never something HA generated)
2. Checks if the base entity ID (without suffix) exists
3. Only shows entities where the base ID is available
4. Skips runs where a `_1` sibling exists, since that means the device or integration did the numbering rather than Home Assistant (`sensor.relay_1` alongside `sensor.relay_2`)
5. Skips tails that continue a MAC address (`device_tracker.athena_clients_0c_80_2f_01_da_12`) or a port number after `tcp` / `udp` (`switch.block_dns_udp_53`)
6. Skips any candidate that would collide with another (e.g. both `sensor.x_2` and `sensor.x_3` targeting the same missing `sensor.x`)
7. Lets you interactively select which ones to fix

**Example output:**

```
Found 8 entities with numeric suffix:
======================================================================
⚠️  WARNING: Not all suffixes are duplicates!
   Some are legitimate (e.g., button_4, sim_2, pm2_5)
   Review carefully before selecting.
======================================================================

  [ 1] sensor.living_room_temperature_2
       -> sensor.living_room_temperature (mqtt)
  [ 2] light.bedroom_lamp_3
       -> light.bedroom_lamp (hue)
  [ 3] sensor.tomorrow_io_home_pm2_5
       -> sensor.tomorrow_io_home_pm2 (tomorrowio)  ⚠️ LEGITIMATE!
  [ 4] button.remote_button_4
       -> button.remote_button (zigbee)  ⚠️ LEGITIMATE!
  ...

Enter selection:
  - Numbers: 1,3,5 or 1-5 or 1,3-5,8
  - 'all' to fix all (DANGEROUS!)
  - 'none' or Enter to skip

Selection: 1,2

Will fix 2 entities:
  - sensor.living_room_temperature_2 -> sensor.living_room_temperature
  - light.bedroom_lamp_3 -> light.bedroom_lamp

⚠️  Fix these 2 entities? [y/N]: y
[2026-05-09 12:00:00] Stopping Home Assistant...
[2026-05-09 12:00:05] ✓ Fixed 2 entity suffixes
[2026-05-09 12:00:05] Starting Home Assistant...
[2026-05-09 12:00:10] Done!
```

**Selection syntax:**
- Single: `1` or `5`
- Multiple: `1,3,5`
- Range: `1-5` (fixes 1, 2, 3, 4, 5)
- Mixed: `1,3-5,8` (fixes 1, 3, 4, 5, 8)
- All: `all` (dangerous)
- None: `none` or just press Enter

**Important:** Always review the list carefully! Some suffixes are legitimate:
- `button_4` - button number 4 on a remote
- `sim_2` - SIM card slot 2
- `pm2_5` - PM2.5 air quality sensor
- `co2_2` - CO2 sensor (not a duplicate)

**When to use:**
- After removing and re-adding an integration
- When you see duplicate-looking entity IDs
- After running option 3 (clean deleted registry items)

**Tip:** Run option 3 first to clean deleted_entities, then re-add your integration. This often prevents the suffix from appearing in the first place.

---

### Option 8: Restore from Backup

See the [Restore from Backup](#restore-from-backup) section above for full details.

---

## What Gets Cleaned

### Orphaned Entities
Entities that reference:
- Deleted devices (device_id no longer exists)
- Deleted config entries (integration removed)
- Deleted automations/scripts/scenes (ID not found in YAML or UI)

### Numeric Suffix Fix
When you remove and re-add an integration, HA sometimes appends `_2` to entity IDs:
- `sensor.living_room_temperature_2` → `sensor.living_room_temperature`

**Important:** Not all `_N` suffixes are duplicates! Some are legitimate:
- `button_4` - button number 4
- `sim_2` - SIM slot 2
- `pm2_5` - PM2.5 sensor

That's why this feature uses interactive selection.

### Deleted Registry Items
Soft-deleted entries in:
- `core.entity_registry` (deleted_entities)
- `core.device_registry` (deleted_devices)

### Database Purge
Old records based on your `recorder.purge_keep_days` setting:
- States older than X days
- Events older than X days
- Orphaned state_attributes and event_data (cleaned with optimised queries)
- VACUUM to reclaim disk space (with disk space check)

---

## Config Path Detection

The script automatically detects your Home Assistant config directory:

| Installation | Config Path |
|--------------|-------------|
| **HAOS** | `/homeassistant` |
| **Docker** | `/config` |
| **Core** | `~/.homeassistant` |

---

## Verification record

**Tested On**: Home Assistant 2026.8.2, `--run=2/3/4 --yes` (and interactively) on a live 5.9 GB database — 49 deleted entities + 4 deleted devices cleaned, 8.4M states + 3M orphan rows purged and VACUUMed (5938.5 → 2839.9 MB), registry and DB integrity verified before/after, HA restarted clean each time. Option 5 tested separately on 2026.8.3, same box: found and removed 4 orphaned statistics (44 long-term rows, left over from a retired device) after confirming all four were genuinely absent from the entity registry, then a follow-up dry run found nothing left, and HA restarted clean. The 1.8.1 fix confirmed on that same box's real Python 3.14.7 on 2026-09-03: `sys.stdin.isatty()` reports `False` under a `shell_command:`-style non-interactive invocation, which is what the fix relies on to tell that case apart from a real terminal. The 1.8.2 fix confirmed with a live `--run=3 --yes` on that same box on 2026-09-04, now running Home Assistant 2026.9.0: cleaned 143 deleted entities and 1 deleted device, HA stopped and restarted clean in about 10 seconds either way. That's well under both the old 60-second and new 180-second start timeout, so it confirms no regression on a normal-speed box, not the slow-boot case from Discussion #3 that the timeout split was actually for.
