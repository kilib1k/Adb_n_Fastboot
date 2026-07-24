# ADB & Fastboot — Community Edition

![Version](https://img.shields.io/badge/version-v5.1.0-blue)
![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)

**A free, open-source GUI for ADB & Fastboot** — built for power users who want the comfort of a desktop tool without memorizing dozens of command-line flags. Originally conceived by [@LineXin](https://github.com/LineXin) [Telegram](https://t.me/LineXin1); the Community Edition is maintained and extended by [@Kilib1k](https://github.com/kilib1k) [Telegram](https://t.me/Kilib1k) .

**[Читать на русском](READMEru.md)**

---

## 📸 Screenshots

| Main window (Device tab) | Logcat viewer | Debloat presets |
|:---:|:---:|:---:|
| ![Main](docs/screenshots/main.png) | ![Logcat](docs/screenshots/logcat.png) | ![Debloat](docs/screenshots/debloat.png) |

| File explorer | Wireless ADB | Partition manager |
|:---:|:---:|:---:|
| ![Explorer](docs/screenshots/explorer.png) | ![Wireless](docs/screenshots/wireless.png) | ![Partitions](docs/screenshots/partitions.png) |

---

## ✨ Features

### ADB functions
- **APK installer** — pick a `.apk`, click install, done.
- **ADB sideload** — flash `.zip` firmware via recovery sideload.
- **Logcat viewer** — live streaming with level/tag/PID/search filters, pause/resume, save to file. Batching & `QPlainTextEdit` keep it smooth even on weak CPUs (Pentium-class OK).
- **File explorer** — navigate `/sdcard` and beyond, push/pull/delete/mkdir with context menu and drag-friendly UX.
- **Wireless ADB** — enable TCP/IP mode, scan QR-less connect by `IP:port`, disconnect one or all.
- **Debloat presets** — curated lists for **Google Apps**, **Google Telemetry**, **Carrier/Partner**, **AOSP Optional**, **Samsung**, **Xiaomi/MIUI/HyperOS**. All operations are reversible: Disable → Enable, Uninstall (user 0) → Reinstall. Each package is tagged `Safe` or `Caution`.
- **Screenshot** — one-click capture to PNG.
- **Bypass setup wizard** — for fresh GSI flashes.
- **Package manager** — full disable/enable/toggle for any installed package.

### Fastboot utilities
- **Partition manager** — flash/erase individual partitions with image picker.
- **Bootloader unlock/relock** — with explicit warnings (Knox counter, data wipe, brick risk).
- **A/B slot switch** — active slot detection and swap.
- **GSI installer** — install Generic System Images on A/B and A-only devices, with `wipe data` option.
- **Unlock ability check** — reads `Device unlocked`, `Device critical unlocked`, `get_unlock_ability`.

### GUI / UX
- **8 themes** — Gray (default), Dark, Light, Green, Blue, Purple, Orange, Cyan.
- **RU / EN localization** — switch on the fly, every label and dialog.
- **Live console log** — every `adb`/`fastboot` command and its output, saveable to file.
- **Auto-update** — checks GitHub Releases once a day, shows changelog, downloads in-place.

---

## 📦 Requirements

- **Windows** 7/10/11
- **Python 3.8+**
- **PyQt5**: `pip install PyQt5`
- **ADB and Fastboot** binaries — already bundled in the program folder, or download [latest platform-tools](https://developer.android.com/tools/releases/platform-tools).
- **USB drivers** for your device (Windows often needs [Google USB driver](https://developer.android.com/studio/run/win-usb) for ADB).
- **USB debugging** enabled in Developer Options.

---

## 🚀 Installation

### Option A — download the script
1. Go to [Releases](https://github.com/kilib1k/Adb_n_Fastboot/releases).
2. Download `AdbFastboot_v5.py` and `localization.json` into the same folder.
3. Make sure `adb.exe` and `fastboot.exe` are in that folder (or in `PATH`).
4. Run:
   ```cmd
   pip install PyQt5
   python AdbFastboot_v5.py
   ```

### Option B — clone the repo
```bash
git clone https://github.com/kilib1k/Adb_n_Fastboot.git
cd Adb_n_Fastboot
pip install PyQt5
python AdbFastboot_v5.py
```

---

## 🧭 Quick start

1. **Enable USB debugging** on your phone (Settings → About → tap Build 7 times → Developer Options → USB debugging).
2. **Connect via USB**, accept the RSA prompt on the phone.
3. **Run the program.** The status panel should switch from `Offline` to `ADB`.
4. **Try the Device tab** — install an APK, open Logcat, or browse `/sdcard` via File Explorer.

### Common commands reference

| Action | Menu / button | Underlying command |
|---|---|---|
| Reboot to bootloader | Device → BOOTLOADER | `adb reboot bootloader` |
| Reboot to recovery | Device → RECOVERY | `adb reboot recovery` |
| Take screenshot | Device → 📸 Screenshot | `adb shell screencap -p /sdcard/screen.png` + `adb pull` |
| Wireless connect | Device → Wireless ADB | `adb tcpip 5555` → `adb connect IP:5555` |
| Disable bloatware | Device → Debloat Presets | `adb shell pm disable-user --user 0 <pkg>` |
| Unlock bootloader | Device → UNLOCK BOOTLOADER | `fastboot flashing unlock` |
| Flash GSI | GSI tab | `fastboot flash system system.img` (active slot) |

---

## 🔧 Auto-updates

The app checks `https://raw.githubusercontent.com/kilib1k/Adb_n_Fastboot/main/update.json` once per day and offers to download any newer version. Old script is saved as `AdbFastboot_v5.py.bak` before replacement.

**For maintainers / forks:** edit the `UPDATE_MANIFEST_URL` constant at the top of `AdbFastboot_v5.py` to point at your own `update.json`. See `update.json` for the schema.

---

## 🩹 Troubleshooting

| Symptom | Fix |
|---|---|
| `adb not found` in status | Place `adb.exe` next to the script, or add to `PATH`. |
| Device shows `unauthorized` | Revoke USB debugging authorizations on phone, reconnect, accept RSA prompt. |
| Status stuck on `Offline` | Reinstall USB drivers; try another USB cable/port; disable USB debugging toggle and re-enable. |
| Logcat stutters | Lower the in-dialog flush interval, or close other apps. Pentium-class CPUs are at the edge of usable. |
| PyQt5 install fails on Python 3.13+ | Use Python 3.12 LTS — PyQt5 wheels lag behind bleeding-edge Python releases. |
| Reboot to bootloader goes to system | Fixed in v5 — commands are now lowercased defensively. Update if you're on v4. |
| `pm disable-user` fails | Some carrier-locked phones restrict `pm`. Use `pm uninstall -k --user 0` instead (also reversible). |

---

## 📜 Changelog

### v5.1 (2026-07-24) — Community Edition
- ➕ **Added colors to Logcat**
- ➕ **Added Linux support**
- ➕ **Removed unnecessary code**

### v5.0 (2026-07-24) — Community Edition
- ➕ **Logcat viewer** with live filters, batching, save-to-file.
- ➕ **Wireless ADB** dialog (enable/connect/disconnect).
- ➕ **File explorer** for `/sdcard` and beyond.
- ➕ **Debloat presets** — Google/Carrier/AOSP/Samsung/Xiaomi, reversible.
- ➕ **Auto-update** via GitHub Releases.
- ➕ **Screenshot** button.
- 🐛 **Fixed reboot-mode bug** — uppercase letters in localized button labels (e.g. `BootLoader`) caused Android to reboot into system instead of bootloader. Commands are now defensively lowercased.
- ➕ RU/EN localization expanded to all dialogs.

---

## ⚠️ Disclaimer

**Modifying your device with ADB and especially Fastboot can brick it, wipe data, or trigger hardware-level fuses (e.g. Samsung Knox).** The authors of this tool are not responsible for any damage.

In particular:
- **Unlocking the bootloader wipes all user data.**
- **Relocking the bootloader on non-stock firmware may brick some devices.**
- **Flashing the wrong partition (`boot`, `system`, `modem`, `xbl`) can require EDL/BROM recovery or be unrecoverable.**
- **Samsung devices** — relocking triggers Knox counter permanently, voiding warranty.
- **Xiaomi devices** — `get_unlock_ability` requires 168-hour Mi Unlock wait; this tool cannot bypass that.

Always have a backup. Always verify image checksums before flashing. When in doubt, **don't**.

---

## 👥 Credits

- **Original idea & first sources** — [@LineXin](https://github.com/LineXin) [Telegram](https://t.me/LineXin1).
- **Community Edition** — [@Kilib1k](https://github.com/kilib1k) — Maaany features, bugfixes, ongoing maintenance.
- **PyQt5** — Riverbank Computing.

The "Community Edition" name reflects that this is an open continuation of an abandoned project. Contributions, issues, and PRs are welcome.

---

**⭐ If this tool saved you time, consider starring the repo.**
