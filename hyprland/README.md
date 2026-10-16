# DevWatch for Hyprland & Waybar

This folder contains a standalone Python script designed to run in Hyprland using **Waybar**.

Since the core DevWatch project is written as a GNOME Shell extension (using GJS and GNOME's specific `gi` libraries), this Python port brings the exact same process tracking, port monitoring, and build detection logic to Arch Linux systems running Hyprland.

## Prerequisites

The only dependencies are Python 3 and standard Linux tools (already present on Arch Linux).

```bash
sudo pacman -S python iproute2
```

## How to use

1. Make the script executable:
   ```bash
   chmod +x ~/.config/waybar/waybar_devwatch.py
   ```
   *(Or wherever you placed the script)*

2. Add a custom module to your Waybar configuration (usually `~/.config/waybar/config` or `~/.config/waybar/config.jsonc`):

```jsonc
"custom/devwatch": {
    "exec": "/path/to/DevWatch/hyprland/waybar_devwatch.py",
    "return-type": "json",
    "format": "{}",
    "tooltip": true,
    "restart-interval": 2
}
```

3. Add it to your modules list (e.g. `modules-right`):

```jsonc
"modules-right": [
    "network",
    "cpu",
    "memory",
    "custom/devwatch",
    "clock"
]
```

4. Optionally, style it in your `~/.config/waybar/style.css`:

```css
#custom-devwatch {
    color: #a6e3a1; /* Green */
    padding: 0 10px;
}
#custom-devwatch.warning {
    color: #f9e2af; /* Yellow for high CPU */
}
#custom-devwatch.critical {
    color: #f38ba8; /* Red for extremely high CPU / build */
}
```

## Features

- **Project Grouping**: Reads `/proc` and groups running user processes by their Git root or project marker files (`package.json`, `Cargo.toml`, etc.).
- **Resource Monitoring**: Tracks CPU percentage and RAM usage per project.
- **Port Monitoring**: Parses `ss -Htulnp` to identify listening dev ports linked to your projects.
- **Build Detection**: Highlights projects that are actively running builds (e.g., `npm`, `cargo`, `make`).
