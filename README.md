<p align="center">
  <h1 align="center">DevWatch (Hyprland & Waybar Edition)</h1>
  <p align="center"><strong>Your projects. Your ports. Your builds. All in one glance.</strong></p>
  <p align="center">A developer-aware live status monitor and interactive GUI dashboard for Arch Linux, Hyprland, and Waybar.</p>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="MIT License"></a>
  <a href="https://hyprland.org"><img src="https://img.shields.io/badge/Hyprland-Compatible-00C853.svg?logo=archlinux&logoColor=white" alt="Hyprland"></a>
  <a href="https://github.com/Alexays/Waybar"><img src="https://img.shields.io/badge/Waybar-Supported-blue.svg" alt="Waybar"></a>
  <a href="https://archlinux.org"><img src="https://img.shields.io/badge/Platform-Arch%20Linux-1793D1.svg?logo=archlinux&logoColor=white" alt="Arch Linux"></a>
</p>

---

## What is DevWatch for Hyprland?

**DevWatch for Hyprland** brings the developer-intelligence dashboard originally designed for GNOME Shell directly to **Hyprland** and **Waybar** users on Arch Linux.

It provides a lightweight background daemon that pipes live metrics to your **Waybar** top panel, plus an interactive popup GUI dashboard built with GTK:

- 🔍 **Running Projects** — Active projects grouped by git root / markers, with process counts, memory usage, and CPU %.
- 🌐 **Open Ports** — Every listening dev port (Vite, Next.js, Flask, PostgreSQL, Redis, Docker, etc.) with runtime elapsed and a 1-click **Stop** button.
- ⚡ **Build Activity** — Real-time tracking of active builds (`npm`, `cargo`, `make`, `go`, `webpack`, `vite`, `tsc`, `gcc`, etc.) with CPU and memory usage.
- ⌨ **Terminal Integration** — 1-click launch of your preferred terminal (`kitty`, `alacritty`, `foot`, `wezterm`) right at the project root.
- ⚠ **Problems & Spikes** — Proactive alerts for memory spikes (>1 GB) or high CPU usage (>80%).
- 🟢🟡🔴 **Live Health Status** — Visual status dot directly in Waybar and on the popup panel.

---

## Interface Overview

### 1. Waybar Status Indicator
Waybar shows live active projects and dev ports at a glance:
```
💻 1 | 🌐 2
```
* **Hovering** reveals a detailed tooltip breakdown of projects, PIDs, memory, and CPU.
* **Clicking** the widget opens the interactive GUI dashboard.

### 2. Interactive GUI Dashboard
Press **`Super + E`** or click the Waybar widget to toggle the interactive floating dashboard:
- **Stop All**: Terminates all running project processes.
- **Project Cards**: Expandable cards with process breakdown, live CPU/RAM metrics, `⌨ Terminal` button, and `Stop` button.
- **Port Manager**: See all occupied ports with their process names and a 1-click `Stop` action.
- **Auto-Hide**: Press `Escape` or click away to dismiss.

---

## Installation & Setup on Arch Linux

### Step 1 — Dependencies
Ensure Python, GTK, and networking tools are installed:

```bash
sudo pacman -S --needed python python-gobject gtk3 iproute2 waybar
```

*(Optional: terminal emulator such as `kitty`, `alacritty`, or `foot` for the `⌨ Terminal` button).*

### Step 2 — Clone the Repository

```bash
git clone https://github.com/Jeevan-ZGDX/Devwatch-Hyperland.git
cd Devwatch-Hyperland
```

### Step 3 — Install Executables to `~/.local/bin`

Copy the Waybar daemon and GUI panel scripts to your local bin directory:

```bash
mkdir -p ~/.local/bin
cp hyprland/waybar_devwatch.py ~/.local/bin/waybar_devwatch.py
cp hyprland/devwatch_panel.py ~/.local/bin/devwatch_panel.py
chmod +x ~/.local/bin/waybar_devwatch.py ~/.local/bin/devwatch_panel.py
```

---

## Configuration

### 1. Configure Waybar (`~/.config/waybar/config`)

Add the custom DevWatch module to your Waybar configuration:

```jsonc
"custom/devwatch": {
    "exec": "/home/vampire/.local/bin/waybar_devwatch.py",
    "return-type": "json",
    "format": "{}",
    "tooltip": true,
    "on-click": "/home/vampire/.local/bin/devwatch_panel.py"
}
```

Add `"custom/devwatch"` into your `modules-right` or `modules-left` list:

```jsonc
"modules-right": [
    "custom/devwatch",
    "cpu",
    "memory",
    "clock"
]
```

### 2. Style DevWatch in Waybar (`~/.config/waybar/style.css`)

Add custom colors and status highlights:

```css
#custom-devwatch {
    color: #fab387;
    font-weight: bold;
    background: rgba(250, 179, 135, 0.1);
    border: 1px solid rgba(250, 179, 135, 0.3);
    border-radius: 8px;
    padding: 0 12px;
    margin: 4px 3px;
}

#custom-devwatch.normal {
    color: #a6e3a1;
    background: rgba(166, 227, 161, 0.1);
    border: 1px solid rgba(166, 227, 161, 0.3);
}

#custom-devwatch.warning {
    color: #f9e2af;
    background: rgba(249, 226, 175, 0.15);
    border: 1px solid rgba(249, 226, 175, 0.4);
}

#custom-devwatch.critical {
    color: #f38ba8;
    background: rgba(243, 139, 168, 0.15);
    border: 1px solid rgba(243, 139, 168, 0.4);
}
```

### 3. Configure Hyprland (`~/.config/hypr/hyprland.conf`)

Add the autostart and shortcut to your `hyprland.conf`:

```ini
# Autostart Waybar
exec-once = waybar

# DevWatch: Toggle Interactive Panel (Super + E)
bind = $mainMod, E, exec, ~/.local/bin/devwatch_panel.py

# DevWatch Floating Window Rules
windowrulev2 = float, class:^(io.github.devwatch.panel)$
windowrulev2 = size 420 650, class:^(io.github.devwatch.panel)$
windowrulev2 = move 100%-430 40, class:^(io.github.devwatch.panel)$
windowrulev2 = pin, class:^(io.github.devwatch.panel)$
windowrulev2 = noborder, class:^(io.github.devwatch.panel)$
```

---

## Reloading Waybar

To reload Waybar cleanly and ensure only **one** instance runs:

```bash
killall -9 waybar 2>/dev/null; while pgrep -x waybar >/dev/null; do sleep 0.1; done; waybar &
```

Or run the included restart helper script:
```bash
~/.local/bin/restart_waybar.sh
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| **`Super + E`** | Toggle the interactive DevWatch panel |
| **`Escape`** | Close the panel when open |
| **Mouse Click on Waybar** | Toggle the interactive DevWatch panel |

---

## Project Structure

```
DevWatch/
├── hyprland/
│   ├── waybar_devwatch.py     ← Waybar daemon (streams JSON metrics & tooltip)
│   ├── devwatch_panel.py      ← Interactive GTK dashboard popup
│   └── README.md              ← Quickstart guide for Hyprland setup
│
├── core/                      ← Original GNOME core logic modules
│   ├── projectDetector.js
│   ├── processTracker.js
│   ├── portMonitor.js
│   ├── buildDetector.js
│   └── snapshotManager.js
│
├── ui/                        ← Original GNOME St/Clutter UI renderers
├── extension.js               ← GNOME Shell extension entry point
└── Makefile                   ← GNOME build commands
```

---

## Privacy & Performance

- **100% Local**: No telemetry, no background network connections, zero analytics.
- **Ultra-lightweight**: Reads `/proc` and `ss` asynchronously with minimal CPU impact.
- **Resource Aware**: Skips idle background processes and only tracks active development workflows.

---

## License

[MIT](LICENSE) © 2026 [Adithya Balan](https://github.com/Adithya-Balan) & [Jeevan-ZGDX](https://github.com/Jeevan-ZGDX)
