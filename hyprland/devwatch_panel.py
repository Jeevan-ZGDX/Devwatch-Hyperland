#!/usr/bin/env python3
"""
DevWatch Panel — GTK3 interactive dashboard for Hyprland.

Replicates the GNOME Shell DevWatch extension as a standalone popup panel
with live-updating project cards, port monitoring, build detection, and
interactive controls (Stop, Open Terminal).
"""

import os
import sys
import signal
import subprocess
import json
import time
import re
from pathlib import Path
from collections import defaultdict

import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gio, Gdk, Pango

# ── Constants ────────────────────────────────────────────────────────────────

APP_ID = 'io.github.devwatch.panel'

DEV_PORTS = {
    80, 443, 3000, 3001, 3002, 3003, 4000, 4200, 5000, 5001,
    5173, 8000, 8080, 8081, 8888, 9000, 9090, 4173, 6006,
    5432, 3306, 6379, 27017, 9200, 9300, 6443, 8001, 2375, 2376,
}

PROJECT_MARKERS = [
    '.git', 'package.json', 'Cargo.toml', 'go.mod',
    'pyproject.toml', 'setup.py', 'pom.xml', 'build.gradle',
    'Makefile', 'CMakeLists.txt', 'composer.json', 'Gemfile',
]

BUILD_TOOLS = {
    'npm', 'npx', 'yarn', 'pnpm', 'bun', 'webpack', 'vite', 'esbuild',
    'rollup', 'parcel', 'tsc', 'cargo', 'rustc', 'go', 'make', 'cmake',
    'gcc', 'g++', 'clang', 'mvn', 'gradle', 'python', 'pip',
    'ninja', 'javac', 'kotlinc', 'pip3', 'pytest', 'docker', 'podman',
    'bundle', 'rake', 'composer', 'bazel',
}

FRIENDLY_NAMES = {
    'node': 'Node.js Server', 'python3': 'Python Server', 'python': 'Python Server',
    'ruby': 'Ruby Server', 'java': 'Java Server', 'go': 'Go Server',
    'cargo': 'Cargo Build', 'rustc': 'Rust Compiler', 'gcc': 'GCC Compiler',
    'g++': 'G++ Compiler', 'clang': 'Clang Compiler', 'make': 'Make Build',
    'cmake': 'CMake', 'npm': 'npm', 'yarn': 'Yarn', 'pnpm': 'pnpm',
    'vite': 'Vite Dev Server', 'webpack': 'Webpack', 'tsc': 'TypeScript Compiler',
    'docker': 'Docker', 'podman': 'Podman', 'nginx': 'Nginx',
    'postgres': 'PostgreSQL', 'redis-server': 'Redis', 'mongod': 'MongoDB',
}

PANEL_WIDTH = 420
POLL_INTERVAL_MS = 5000

# ── Data Layer ───────────────────────────────────────────────────────────────

cwd_cache = {}
prev_jiffies = {}
prev_total_jiffies = 0
port_first_seen = {}


def get_project_root(cwd):
    if not cwd or cwd == '/':
        return None
    if cwd in cwd_cache:
        return cwd_cache[cwd]
    current = Path(cwd)
    while current.parent != current:
        if str(current) in ('/', '/home', '/usr', '/tmp', '/var', '/opt'):
            break
        for marker in PROJECT_MARKERS:
            if (current / marker).exists():
                cwd_cache[cwd] = str(current)
                return str(current)
        current = current.parent
    cwd_cache[cwd] = None
    return None


def read_total_cpu():
    try:
        with open('/proc/stat') as f:
            for line in f:
                if line.startswith('cpu '):
                    return sum(int(x) for x in line.split()[1:])
    except Exception:
        pass
    return 0


def scan_processes():
    global prev_total_jiffies
    total_jiffies = read_total_cpu()
    delta_total = max(total_jiffies - prev_total_jiffies, 1)
    prev_total_jiffies = total_jiffies
    num_cpus = os.cpu_count() or 1

    processes = []
    live_pids = set()

    for pid_str in os.listdir('/proc'):
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        if pid < 2:
            continue
        try:
            live_pids.add(pid)
            with open(f'/proc/{pid}/stat') as f:
                content = f.read()
                close_paren = content.rfind(')')
                fields = content[close_paren + 2:].split()
                utime = int(fields[11])
                stime = int(fields[12])
                raw_jiffies = utime + stime

            prev = prev_jiffies.get(pid, raw_jiffies)
            delta = max(raw_jiffies - prev, 0)
            cpu_pct = round((delta / delta_total) * num_cpus * 100, 1)
            prev_jiffies[pid] = raw_jiffies

            vm_rss = 0
            name = f'[{pid}]'
            with open(f'/proc/{pid}/status') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        vm_rss = int(line.split()[1])
                    elif line.startswith('Name:'):
                        name = line.split('\t')[1].strip()

            cwd = os.readlink(f'/proc/{pid}/cwd')

            try:
                with open(f'/proc/{pid}/cmdline', 'rb') as f:
                    cmdline = f.read().decode('utf-8', errors='replace').split('\0')
                    cmdline = [c for c in cmdline if c]
            except Exception:
                cmdline = [name]

            root = get_project_root(cwd)
            if root:
                processes.append({
                    'pid': pid, 'name': name, 'root': root,
                    'cpu': cpu_pct, 'mem': vm_rss, 'cmdline': cmdline,
                })
        except Exception:
            pass

    for p in list(prev_jiffies.keys()):
        if p not in live_pids:
            del prev_jiffies[p]
    return processes


SS_LINE_RE = re.compile(
    r'^(tcp|udp)\s+\S+\s+\d+\s+\d+\s+(\S+):(\d+)\s+\S+'
    r'(?:\s+users:\(\("([^"]+)",pid=(\d+),fd=\d+\)\))?'
)


def scan_ports():
    ports = []
    try:
        out = subprocess.check_output(
            ['ss', '-Htulnp'], stderr=subprocess.DEVNULL
        ).decode('utf-8')
        now = time.monotonic()
        for line in out.splitlines():
            m = SS_LINE_RE.match(line)
            if not m:
                continue
            protocol = m.group(1)
            address = m.group(2)
            port = int(m.group(3))
            proc_name = m.group(4)
            pid = int(m.group(5)) if m.group(5) else None
            key = f'{protocol}:{port}:{pid or 0}'
            if key not in port_first_seen:
                port_first_seen[key] = now
            runtime = now - port_first_seen[key]
            ports.append({
                'port': port, 'protocol': protocol, 'address': address,
                'pid': pid, 'process_name': proc_name,
                'is_dev': port in DEV_PORTS, 'runtime': runtime,
            })
    except Exception:
        pass
    return sorted(ports, key=lambda p: p['port'])


def format_runtime(seconds):
    if seconds < 60:
        return f'{int(seconds)}s'
    if seconds < 3600:
        return f'{int(seconds // 60)}m {int(seconds % 60)}s'
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    return f'{h}h {m}m'


def format_mem(kb):
    if kb < 1024:
        return f'{kb} KB'
    mb = kb / 1024
    if mb < 1024:
        return f'{mb:.1f} MB'
    return f'{mb / 1024:.2f} GB'


def friendly_name(proc):
    name = proc.get('name', '').lower()
    if name in FRIENDLY_NAMES:
        return FRIENDLY_NAMES[name]
    return proc.get('name', 'Unknown')


def kill_pid(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except PermissionError:
        subprocess.run(['kill', str(pid)], capture_output=True)


def kill_project(project_data):
    for proc in project_data.get('processes', []):
        kill_pid(proc['pid'])


def open_terminal(path):
    terminals = ['kitty', 'alacritty', 'foot', 'wezterm', 'xterm']
    for term in terminals:
        if subprocess.run(['which', term], capture_output=True).returncode == 0:
            if term == 'kitty':
                subprocess.Popen(['kitty', '--directory', path])
            elif term == 'alacritty':
                subprocess.Popen(['alacritty', '--working-directory', path])
            elif term == 'foot':
                subprocess.Popen(['foot', '--working-directory', path])
            elif term == 'wezterm':
                subprocess.Popen(['wezterm', 'start', '--cwd', path])
            else:
                subprocess.Popen([term], cwd=path)
            return
    subprocess.Popen(['xdg-open', path])


# ── CSS ──────────────────────────────────────────────────────────────────────

CSS = """
.devwatch-panel {
    background-color: #1e1e2e;
    border-radius: 12px;
}

.header-box {
    background-color: #313244;
    border-radius: 10px;
    padding: 14px 16px;
    margin: 4px;
}

.header-title {
    font-size: 16px;
    font-weight: bold;
    color: #cdd6f4;
}

.header-subtitle {
    font-size: 11px;
    color: #a6adc8;
}

.stats-label {
    font-size: 11px;
    color: #89b4fa;
    font-weight: 600;
}

.section-title {
    font-size: 13px;
    font-weight: bold;
    color: #fab387;
    padding: 4px 8px;
}

.project-card {
    background-color: #313244;
    border-radius: 8px;
    padding: 10px 12px;
    margin: 3px 6px;
}

.project-card:hover {
    background-color: #45475a;
}

.project-name {
    font-size: 13px;
    font-weight: bold;
    color: #cdd6f4;
}

.project-stats {
    font-size: 11px;
    color: #a6adc8;
}

.process-row {
    font-size: 11px;
    color: #bac2de;
}

.port-row {
    background-color: #313244;
    border-radius: 6px;
    padding: 8px 12px;
    margin: 2px 6px;
}

.port-number {
    font-size: 13px;
    font-weight: bold;
    color: #a6e3a1;
}

.port-number-dev {
    font-size: 13px;
    font-weight: bold;
    color: #f9e2af;
}

.port-info {
    font-size: 11px;
    color: #a6adc8;
}

.build-row {
    background-color: rgba(250, 179, 135, 0.08);
    border-radius: 6px;
    padding: 8px 12px;
    margin: 2px 6px;
}

.build-tool {
    font-size: 12px;
    font-weight: bold;
    color: #fab387;
}

.build-info {
    font-size: 11px;
    color: #a6adc8;
}

.alert-box {
    background-color: rgba(243, 139, 168, 0.12);
    border-radius: 6px;
    padding: 8px 12px;
    margin: 2px 6px;
}

.alert-text {
    font-size: 12px;
    color: #f38ba8;
}

.alert-warn {
    background-color: rgba(249, 226, 175, 0.12);
}

.alert-warn-text {
    font-size: 12px;
    color: #f9e2af;
}

.btn-stop {
    background-color: rgba(243, 139, 168, 0.2);
    color: #f38ba8;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: bold;
    border: none;
}

.btn-stop:hover {
    background-color: rgba(243, 139, 168, 0.4);
}

.btn-terminal {
    background-color: rgba(137, 180, 250, 0.15);
    color: #89b4fa;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: bold;
    border: none;
}

.btn-terminal:hover {
    background-color: rgba(137, 180, 250, 0.35);
}

.btn-stop-all {
    background-color: rgba(243, 139, 168, 0.15);
    color: #f38ba8;
    border-radius: 8px;
    padding: 6px 14px;
    font-size: 12px;
    font-weight: bold;
    border: none;
}

.btn-stop-all:hover {
    background-color: rgba(243, 139, 168, 0.35);
}

.btn-close {
    background-color: rgba(108, 112, 134, 0.3);
    color: #cdd6f4;
    border-radius: 6px;
    padding: 4px 10px;
    font-size: 13px;
    font-weight: bold;
    border: none;
}

.btn-close:hover {
    background-color: rgba(108, 112, 134, 0.6);
}

.status-green { color: #a6e3a1; }
.status-yellow { color: #f9e2af; }
.status-red { color: #f38ba8; }

.empty-state {
    font-size: 12px;
    color: #6c7086;
    padding: 16px;
}

.separator-line {
    background-color: #45475a;
    min-height: 1px;
    margin: 4px 10px;
}
"""

# ── Singleton via lockfile ───────────────────────────────────────────────────

LOCK_FILE = os.path.join(GLib.get_tmp_dir(), 'devwatch-panel.lock')


def read_lock_pid():
    try:
        with open(LOCK_FILE) as f:
            return int(f.read().strip())
    except Exception:
        return None


def write_lock_pid():
    with open(LOCK_FILE, 'w') as f:
        f.write(str(os.getpid()))


def is_pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ── Panel Window ─────────────────────────────────────────────────────────────

class DevWatchPanel(Gtk.Window):
    def __init__(self):
        super().__init__(title='DevWatch')
        self.set_default_size(PANEL_WIDTH, 620)
        self.set_resizable(False)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_type_hint(Gdk.WindowTypeHint.DIALOG)
        self.set_keep_above(True)
        self.get_style_context().add_class('devwatch-panel')

        # Position top-right
        screen = Gdk.Screen.get_default()
        if screen:
            monitor_geo = screen.get_monitor_geometry(screen.get_primary_monitor())
            self.move(monitor_geo.x + monitor_geo.width - PANEL_WIDTH - 10, monitor_geo.y + 40)

        # Scrollable container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        self._content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self._content_box.set_margin_top(6)
        self._content_box.set_margin_bottom(6)
        self._content_box.set_margin_start(4)
        self._content_box.set_margin_end(4)
        scrolled.add(self._content_box)
        self.add(scrolled)

        self._prev_ports = set()
        self._timer_id = None

        # Close on Escape
        self.connect('key-press-event', self._on_key)
        # Close on focus lost
        self.connect('focus-out-event', self._on_focus_out)
        self.connect('delete-event', self._on_delete)
        # Toggle via SIGUSR1
        signal.signal(signal.SIGUSR1, self._on_toggle_signal)

        self._refresh()
        self._timer_id = GLib.timeout_add(POLL_INTERVAL_MS, self._refresh)

        self.show_all()

    def _on_key(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            self._quit()
            return True
        return False

    def _on_focus_out(self, widget, event):
        # Auto-hide on focus loss
        self._quit()
        return False

    def _on_delete(self, widget, event):
        self._quit()
        return True

    def _on_toggle_signal(self, signum, frame):
        # Toggle visibility from external signal
        GLib.idle_add(self._quit)

    def _quit(self):
        try:
            os.unlink(LOCK_FILE)
        except Exception:
            pass
        Gtk.main_quit()

    def _refresh(self):
        procs = scan_processes()
        ports = scan_ports()

        # Group by project
        projects = {}
        pid_to_root = {}
        for p in procs:
            root = p['root']
            pid_to_root[p['pid']] = root
            if root not in projects:
                projects[root] = {
                    'name': Path(root).name, 'root': root,
                    'cpu': 0, 'mem': 0, 'processes': [], 'builds': [],
                }
            projects[root]['cpu'] += p['cpu']
            projects[root]['mem'] += p['mem']
            projects[root]['processes'].append(p)
            if p['name'].lower() in BUILD_TOOLS and p['cpu'] >= 1.0:
                projects[root]['builds'].append(p)

        ports_by_root = defaultdict(list)
        for pt in ports:
            root = pid_to_root.get(pt['pid'])
            if root:
                pt['project_name'] = Path(root).name
                ports_by_root[root].append(pt)

        dev_ports_list = [p for p in ports if p['is_dev']]
        total_mem = sum(p['mem'] for p in projects.values())
        total_cpu = sum(p['cpu'] for p in projects.values())

        # Alerts
        alerts = []
        for root, data in projects.items():
            if data['mem'] > 2 * 1024 * 1024:
                alerts.append(('critical', f"{data['name']} memory usage is high ({format_mem(data['mem'])})"))
            elif data['mem'] > 1024 * 1024:
                alerts.append(('warn', f"{data['name']} memory usage is elevated ({format_mem(data['mem'])})"))
            if data['cpu'] > 80:
                alerts.append(('critical', f"{data['name']} CPU usage is high ({data['cpu']:.1f}%)"))

        # Status
        current_port_set = {(p['protocol'], p['port']) for p in ports if p['is_dev']}
        new_ports = current_port_set - self._prev_ports
        self._prev_ports = current_port_set

        status = 'green'
        if total_cpu > 80 or any(b['cpu'] > 90 for d in projects.values() for b in d['builds']):
            status = 'yellow'
        if new_ports:
            status = 'red'

        # Clear old content
        for child in self._content_box.get_children():
            self._content_box.remove(child)

        # Header
        self._build_header(projects, dev_ports_list, total_mem, total_cpu, status)

        # Alerts
        if alerts:
            self._add_section_title('⚠  Problems')
            for severity, msg in alerts:
                self._add_alert(severity, msg)

        # Projects
        self._add_section_title(f'🔍  Running Projects ({len(projects)})')
        if projects:
            for root, data in sorted(projects.items(), key=lambda x: x[1]['cpu'], reverse=True):
                self._add_project_card(data, ports_by_root.get(root, []))
        else:
            lbl = Gtk.Label(label='No active projects detected')
            lbl.get_style_context().add_class('empty-state')
            self._content_box.pack_start(lbl, False, False, 0)

        # Ports
        self._add_section_title(f'🌐  Open Ports ({len(dev_ports_list)})')
        if dev_ports_list:
            for pt in dev_ports_list:
                self._add_port_row(pt)
        else:
            lbl = Gtk.Label(label='No dev ports are currently open')
            lbl.get_style_context().add_class('empty-state')
            self._content_box.pack_start(lbl, False, False, 0)

        # Builds
        all_builds = [b for d in projects.values() for b in d['builds']]
        if all_builds:
            self._add_section_title(f'⚡  Build Activity ({len(all_builds)})')
            for b in all_builds:
                self._add_build_row(b)

        self._content_box.show_all()
        return True

    # ── UI Builders ──────────────────────────────────────────────────────────

    def _build_header(self, projects, dev_ports, total_mem, total_cpu, status):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.get_style_context().add_class('header-box')

        # Top row
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        dot = Gtk.Label(label='●')
        dot.get_style_context().add_class(f'status-{status}')
        top.pack_start(dot, False, False, 0)

        title = Gtk.Label(label='DevWatch')
        title.get_style_context().add_class('header-title')
        title.set_xalign(0)
        top.pack_start(title, True, True, 0)

        if projects:
            btn_stop = Gtk.Button(label='Stop All')
            btn_stop.get_style_context().add_class('btn-stop-all')
            btn_stop.connect('clicked', lambda _: [kill_project(d) for d in projects.values()])
            top.pack_start(btn_stop, False, False, 0)

        btn_close = Gtk.Button(label='✕')
        btn_close.get_style_context().add_class('btn-close')
        btn_close.connect('clicked', lambda _: self._quit())
        top.pack_start(btn_close, False, False, 0)

        box.pack_start(top, False, False, 0)

        # Subtitle
        sub = Gtk.Label(label='Your projects. Your ports. Your builds. All in one glance.')
        sub.get_style_context().add_class('header-subtitle')
        sub.set_xalign(0)
        box.pack_start(sub, False, False, 2)

        # Stats
        stats_text = f'📊 {len(projects)} projects  ·  🌐 {len(dev_ports)} dev ports  ·  💾 {format_mem(total_mem)}  ·  ⚡ {total_cpu:.1f}% CPU'
        stats = Gtk.Label(label=stats_text)
        stats.get_style_context().add_class('stats-label')
        stats.set_xalign(0)
        stats.set_line_wrap(True)
        box.pack_start(stats, False, False, 2)

        self._content_box.pack_start(box, False, False, 0)

    def _add_section_title(self, text):
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        sep.get_style_context().add_class('separator-line')
        self._content_box.pack_start(sep, False, False, 2)

        lbl = Gtk.Label(label=text)
        lbl.get_style_context().add_class('section-title')
        lbl.set_xalign(0)
        self._content_box.pack_start(lbl, False, False, 0)

    def _add_project_card(self, data, ports):
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        card.get_style_context().add_class('project-card')

        # Title row
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        name_lbl = Gtk.Label(label=data['name'])
        name_lbl.get_style_context().add_class('project-name')
        name_lbl.set_xalign(0)
        name_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        title_row.pack_start(name_lbl, True, True, 0)

        btn_term = Gtk.Button(label='⌨ Terminal')
        btn_term.get_style_context().add_class('btn-terminal')
        root = data['root']
        btn_term.connect('clicked', lambda _, r=root: open_terminal(r))
        title_row.pack_start(btn_term, False, False, 0)

        btn_stop = Gtk.Button(label='Stop')
        btn_stop.get_style_context().add_class('btn-stop')
        btn_stop.connect('clicked', lambda _, d=data: kill_project(d))
        title_row.pack_start(btn_stop, False, False, 0)

        card.pack_start(title_row, False, False, 0)

        # Stats line
        port_str = ''
        if ports:
            port_nums = ', '.join(str(p['port']) for p in ports)
            port_str = f'  ·  🌐 {port_nums}'
        build_str = ''
        if data['builds']:
            tools = ', '.join(b['name'] for b in data['builds'])
            build_str = f'  ·  🔨 {tools}'

        stats_lbl = Gtk.Label(
            label=f"{len(data['processes'])} processes  ·  {format_mem(data['mem'])}  ·  {data['cpu']:.1f}% CPU{port_str}{build_str}"
        )
        stats_lbl.get_style_context().add_class('project-stats')
        stats_lbl.set_xalign(0)
        stats_lbl.set_line_wrap(True)
        card.pack_start(stats_lbl, False, False, 0)

        # Expandable process list
        expander = Gtk.Expander(label=f'  Show {len(data["processes"])} processes')
        proc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        for proc in sorted(data['processes'], key=lambda p: p['cpu'], reverse=True)[:10]:
            fname = friendly_name(proc)
            row_lbl = Gtk.Label(
                label=f'  └─ {fname} (PID {proc["pid"]})  {proc["cpu"]:.1f}%  {format_mem(proc["mem"])}'
            )
            row_lbl.get_style_context().add_class('process-row')
            row_lbl.set_xalign(0)
            row_lbl.set_ellipsize(Pango.EllipsizeMode.END)
            proc_box.pack_start(row_lbl, False, False, 0)
        if len(data['processes']) > 10:
            more = Gtk.Label(label=f'  ... and {len(data["processes"]) - 10} more')
            more.get_style_context().add_class('process-row')
            more.set_xalign(0)
            proc_box.pack_start(more, False, False, 0)
        expander.add(proc_box)
        card.pack_start(expander, False, False, 0)

        self._content_box.pack_start(card, False, False, 0)

    def _add_port_row(self, pt):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.get_style_context().add_class('port-row')

        if pt['is_dev']:
            dot = Gtk.Label(label='●')
            dot.get_style_context().add_class('port-number-dev')
            row.pack_start(dot, False, False, 0)

        port_lbl = Gtk.Label(label=f":{pt['port']}")
        port_lbl.get_style_context().add_class('port-number-dev' if pt['is_dev'] else 'port-number')
        row.pack_start(port_lbl, False, False, 0)

        info_parts = [pt['protocol'].upper()]
        if pt.get('process_name'):
            info_parts.append(pt['process_name'])
        if pt.get('project_name'):
            info_parts.append(f"({pt['project_name']})")
        info_parts.append(format_runtime(pt['runtime']))

        info_lbl = Gtk.Label(label='  ·  '.join(info_parts))
        info_lbl.get_style_context().add_class('port-info')
        info_lbl.set_xalign(0)
        info_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        row.pack_start(info_lbl, True, True, 0)

        if pt['pid']:
            btn = Gtk.Button(label='Stop')
            btn.get_style_context().add_class('btn-stop')
            pid = pt['pid']
            btn.connect('clicked', lambda _, p=pid: kill_pid(p))
            row.pack_start(btn, False, False, 0)

        self._content_box.pack_start(row, False, False, 0)

    def _add_build_row(self, build):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.get_style_context().add_class('build-row')

        tool_lbl = Gtk.Label(label=f"🔨 {build['name']}")
        tool_lbl.get_style_context().add_class('build-tool')
        row.pack_start(tool_lbl, False, False, 0)

        info_lbl = Gtk.Label(label=f"PID {build['pid']}  ·  {build['cpu']:.1f}% CPU  ·  {format_mem(build['mem'])}")
        info_lbl.get_style_context().add_class('build-info')
        info_lbl.set_xalign(0)
        row.pack_start(info_lbl, True, True, 0)

        self._content_box.pack_start(row, False, False, 0)

    def _add_alert(self, severity, msg):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.get_style_context().add_class('alert-box')
        if severity == 'warn':
            box.get_style_context().add_class('alert-warn')

        icon = '🔴' if severity == 'critical' else '🟡'
        lbl = Gtk.Label(label=f'{icon}  {msg}')
        lbl.get_style_context().add_class('alert-text' if severity == 'critical' else 'alert-warn-text')
        lbl.set_xalign(0)
        lbl.set_line_wrap(True)
        box.pack_start(lbl, True, True, 0)

        self._content_box.pack_start(box, False, False, 0)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    # Singleton: if already running, send SIGUSR1 to toggle and exit
    existing_pid = read_lock_pid()
    if existing_pid and is_pid_alive(existing_pid):
        os.kill(existing_pid, signal.SIGUSR1)
        sys.exit(0)

    write_lock_pid()

    # Load CSS
    css_provider = Gtk.CssProvider()
    css_provider.load_from_data(CSS.encode('utf-8'))
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(),
        css_provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )

    panel = DevWatchPanel()
    Gtk.main()


if __name__ == '__main__':
    main()
