# 🧹 Home Assistant Cleanup

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.1+-41BDF5?style=for-the-badge&logo=home-assistant&logoColor=white)](https://www.home-assistant.io/)
[![Python](https://img.shields.io/badge/Python-3.8+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-blue?style=for-the-badge)](LICENSE)

**Automated cleanup script for Home Assistant - Remove orphaned entities, clean registries, purge old database records.**

> **🔥 Solves the common "ghost entities" problem** - entities that persist after removing integrations or devices

[Features](#-features) • [Quick Start](#-quick-start) • [Usage](#-usage) • [Troubleshooting](#-troubleshooting)

### 🎯 Created by [@hiall-fyi](https://github.com/hiall-fyi)

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

*If this script saves you time, consider buying me a coffee! ☕*

---

## 🎯 Features

- 🗑️ **Orphaned entity cleanup** - Removes entities with missing device/config/automation definitions
- 🧹 **Deleted registry cleanup** - Clears `deleted_entities` and `deleted_devices` lists
- 💾 **Database purge** - Removes states/events older than 14 days + VACUUM
- 📦 **Old backup cleanup** - Removes backup files older than 7 days
- 🛡️ **Auto backup** - Backs up registry files before any modifications
- 👀 **Dry-run mode** - Preview all changes without modifying anything

### 📊 What It Cleans

| Resource | Description | Impact |
|----------|-------------|--------|
| **Orphaned Entities** | Entities referencing deleted devices/configs | Cleaner entity list |
| **Deleted Registry Items** | Soft-deleted entries in registries | Smaller registry files |
| **Old Database Records** | States/events older than 14 days | Smaller database, faster queries |
| **Old Backups** | Script-created backups older than 7 days | Disk space savings |

---

## 📋 Prerequisites

- **Home Assistant**: Any installation type (HAOS, Docker, Core)
- **Python**: 3.8 or higher
- **Access**: SSH or terminal access to HA config directory

---

## 🚀 Quick Start

### 1. Download

```bash
# Download to your HA config directory
wget -O ha-cleanup.py https://raw.githubusercontent.com/hiall-fyi/ha-cleanup/main/ha-cleanup.py
chmod +x ha-cleanup.py
```

### 2. Preview Changes (Dry Run)

```bash
python3 ha-cleanup.py --dry-run
```

### 3. Execute Cleanup

```bash
python3 ha-cleanup.py
```

---

## 📖 Usage

### Dry Run Mode (Safe Preview)

Preview what would be removed without making any changes:

```bash
python3 ha-cleanup.py --dry-run
```

**Example Output:**

```
[2026-01-15 20:00:00] ==================================================
[2026-01-15 20:00:00] Home Assistant Cleanup (DRY RUN)
[2026-01-15 20:00:00] ==================================================
[2026-01-15 20:00:00] Config path: /homeassistant
[2026-01-15 20:00:00] Database size: 256.3 MB

[2026-01-15 20:00:00] Found 12 orphaned entities:
[2026-01-15 20:00:00]   - automation: automation.old_automation (Old Automation)
[2026-01-15 20:00:00]   - hue: light.deleted_bulb (Deleted Bulb)
[2026-01-15 20:00:00]   - mqtt: sensor.orphaned_sensor (Orphaned Sensor)
...
[2026-01-15 20:00:00] Would clean 45 deleted entities
[2026-01-15 20:00:00] Would clean 8 deleted devices
[2026-01-15 20:00:00] Would purge 125000 states, 89000 events older than 14 days

[2026-01-15 20:00:00] ==================================================
[2026-01-15 20:00:00] Summary:
[2026-01-15 20:00:00]   Orphaned entities: 12
[2026-01-15 20:00:00]   Deleted registry items: 53
[2026-01-15 20:00:00] ==================================================
[2026-01-15 20:00:00] Done!
```

### Execute Cleanup

Run the actual cleanup (will stop/start HA automatically):

```bash
python3 ha-cleanup.py
```

**What happens:**

1. ✅ Stops Home Assistant
2. ✅ Backs up registry files
3. ✅ Removes orphaned entities
4. ✅ Cleans deleted registry items
5. ✅ Purges old database records
6. ✅ Vacuums database
7. ✅ Removes old backup files
8. ✅ Starts Home Assistant

---

## 🔧 Config Path Detection

The script automatically detects your Home Assistant config directory:

| Installation | Config Path |
|--------------|-------------|
| **HAOS** | `/homeassistant` |
| **Docker** | `/config` |
| **Core** | `~/.homeassistant` |

---

## 🔄 Automation (Optional)

### Cron Job Example

Run cleanup weekly on Sunday at 3 AM:

```bash
# Edit crontab
crontab -e

# Add this line
0 3 * * 0 /usr/bin/python3 /homeassistant/ha-cleanup.py >> /var/log/ha-cleanup.log 2>&1
```

### Home Assistant Shell Command

Add to `configuration.yaml`:

```yaml
shell_command:
  ha_cleanup_dry_run: "python3 /config/ha-cleanup.py --dry-run"
  ha_cleanup: "python3 /config/ha-cleanup.py"
```

---

## 🐛 Troubleshooting

### Script Can't Find Config Directory

```
Error: Could not find Home Assistant config directory
```

**Solution**: Run from within the config directory or modify `CONFIG_PATHS` in the script.

### Permission Denied

```
PermissionError: [Errno 13] Permission denied
```

**Solution**: Run with appropriate permissions:
```bash
sudo python3 ha-cleanup.py
```

### Home Assistant Won't Stop/Start

The script tries multiple methods to stop/start HA:
- `ha core stop/start` (HAOS)
- `systemctl stop/start home-assistant@homeassistant` (Core)
- `docker stop/start homeassistant` (Docker)

If none work, the script will prompt you to stop/start HA manually.

### Database Locked

```
sqlite3.OperationalError: database is locked
```

**Solution**: Ensure Home Assistant is fully stopped before running cleanup.

---

## 📊 Safety Features

| Feature | Description |
|---------|-------------|
| **Auto Backup** | Registry files backed up before modification |
| **Dry Run** | Preview all changes without risk |
| **Graceful Stop** | Properly stops HA before database operations |
| **Error Handling** | Continues on individual failures, reports at end |

---

## 🆘 Support

For issues and questions:

1. Check the [Troubleshooting](#-troubleshooting) section
2. Run with `--dry-run` first to preview changes
3. Open an issue on [GitHub](https://github.com/hiall-fyi/ha-cleanup/issues)

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## ⭐ Star History

If you find this script useful, please consider giving it a star!

[![Star History Chart](https://api.star-history.com/svg?repos=hiall-fyi/ha-cleanup&type=Date)](https://star-history.com/#hiall-fyi/ha-cleanup&Date)

### 💖 Support This Project

If this script saved you from "ghost entity" headaches, consider buying me a coffee! ☕

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

---

**Made with ❤️ by [@hiall-fyi](https://github.com/hiall-fyi)**

*Solving real problems for the Home Assistant community*

**Version**: 1.0.0  
**Last Updated**: 2026-01-15  
**Tested On**: Home Assistant 2024.x (HAOS, Docker, Core)
