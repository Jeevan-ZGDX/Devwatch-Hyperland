#!/usr/bin/env python3
import os
import time
import json
import subprocess
from pathlib import Path
from collections import defaultdict

# Dev ports
DEV_PORTS = {
    80, 443, 3000, 3001, 3002, 3003, 4000, 4200, 5000, 5001,
    5173, 8000, 8080, 8081, 8888, 9000, 9090, 4173, 6006,
    5432, 3306, 6379, 27017, 9200, 9300, 6443, 8001, 2375, 2376
}

PROJECT_MARKERS = [
    '.git', 'package.json', 'Cargo.toml', 'go.mod',
    'pyproject.toml', 'setup.py', 'pom.xml', 'build.gradle',
    'Makefile', 'CMakeLists.txt', 'composer.json', 'Gemfile',
]

BUILD_TOOLS = {
    'npm', 'npx', 'yarn', 'pnpm', 'bun', 'webpack', 'vite', 'esbuild',
    'rollup', 'parcel', 'tsc', 'cargo', 'rustc', 'go', 'make', 'cmake',
    'gcc', 'g++', 'clang', 'mvn', 'gradle', 'python', 'pip'
}

cwd_cache = {}
prev_jiffies = {}
prev_total_jiffies = 0

def get_project_root(cwd):
    if not cwd or cwd == "/":
        return None
    if cwd in cwd_cache:
        return cwd_cache[cwd]
    
    current = Path(cwd)
    while current.parent != current:
        if str(current) in ['/home', '/usr', '/tmp', '/var', '/opt']:
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
        with open('/proc/stat', 'r') as f:
            for line in f:
                if line.startswith('cpu '):
                    return sum(map(int, line.split()[1:]))
    except:
        pass
    return 0

def get_num_cpus():
    try:
        return os.cpu_count() or 1
    except:
        return 1

def scan_processes():
    global prev_total_jiffies
    
    total_jiffies = read_total_cpu()
    delta_total = max(total_jiffies - prev_total_jiffies, 1)
    prev_total_jiffies = total_jiffies
    num_cpus = get_num_cpus()
    
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
            
            with open(f'/proc/{pid}/stat', 'r') as f:
                stat_line = f.read().split(')')[1].split()
                utime = int(stat_line[11])
                stime = int(stat_line[12])
                raw_jiffies = utime + stime
                
            prev = prev_jiffies.get(pid, raw_jiffies)
            delta = max(raw_jiffies - prev, 0)
            cpu_percent = (delta / delta_total) * num_cpus * 100
            prev_jiffies[pid] = raw_jiffies
            
            vm_rss = 0
            name = f"[{pid}]"
            with open(f'/proc/{pid}/status', 'r') as f:
                for line in f:
                    if line.startswith('VmRSS:'):
                        vm_rss = int(line.split()[1])
                    elif line.startswith('Name:'):
                        name = line.split()[1].strip()
                        
            cwd = os.readlink(f'/proc/{pid}/cwd')
            root = get_project_root(cwd)
            
            if root:
                processes.append({
                    'pid': pid,
                    'name': name,
                    'root': root,
                    'cpu': cpu_percent,
                    'mem': vm_rss
                })
        except:
            pass
            
    # Cleanup dead PIDs
    for p in list(prev_jiffies.keys()):
        if p not in live_pids:
            del prev_jiffies[p]
            
    return processes

def scan_ports():
    ports = []
    try:
        out = subprocess.check_output(['ss', '-Htulnp']).decode('utf-8')
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5:
                continue
            
            local_addr = parts[4]
            port = int(local_addr.split(':')[-1])
            
            pid = None
            if 'users:((' in line:
                try:
                    users_str = line.split('users:((')[1].split(')')[0]
                    pid_str = [p for p in users_str.split(',') if p.startswith('pid=')]
                    if pid_str:
                        pid = int(pid_str[0].split('=')[1])
                except:
                    pass
                    
            ports.append({'port': port, 'pid': pid})
    except:
        pass
    return ports

def main():
    while True:
        procs = scan_processes()
        ports = scan_ports()
        
        projects = defaultdict(lambda: {'cpu': 0, 'mem': 0, 'procs': 0, 'builds': []})
        pid_to_root = {}
        
        for p in procs:
            root = p['root']
            pid_to_root[p['pid']] = root
            projects[root]['cpu'] += p['cpu']
            projects[root]['mem'] += p['mem']
            projects[root]['procs'] += 1
            if p['name'].lower() in BUILD_TOOLS and p['cpu'] >= 1.0:
                projects[root]['builds'].append(p['name'])

        dev_ports_active = 0
        ports_by_root = defaultdict(list)
        for pt in ports:
            if pt['port'] in DEV_PORTS:
                dev_ports_active += 1
                root = pid_to_root.get(pt['pid'])
                if root:
                    ports_by_root[root].append(pt['port'])
                    
        total_mem_mb = sum(p['mem'] for p in projects.values()) // 1024
        total_cpu = sum(p['cpu'] for p in projects.values())
        
        # Build Tooltip
        tooltip_lines = []
        tooltip_lines.append(f"<b>DevWatch Status</b>")
        tooltip_lines.append(f"Projects: {len(projects)} | Open Ports: {dev_ports_active}")
        tooltip_lines.append(f"Total Ram: {total_mem_mb} MB | CPU: {total_cpu:.1f}%")
        tooltip_lines.append("")
        
        for root, data in sorted(projects.items(), key=lambda x: x[1]['cpu'], reverse=True):
            name = Path(root).name
            mem_mb = data['mem'] // 1024
            build_str = f" [🔨 {','.join(data['builds'])}]" if data['builds'] else ""
            ports_str = f" 🌐 {','.join(map(str, ports_by_root[root]))}" if ports_by_root[root] else ""
            tooltip_lines.append(f"<b>{name}</b>{build_str}{ports_str}")
            tooltip_lines.append(f"  └─ {data['procs']} procs | {mem_mb} MB | {data['cpu']:.1f}% CPU")
            
        tooltip = "\n".join(tooltip_lines)
        text = f"💻 {len(projects)} | 🌐 {dev_ports_active}"
        
        # Indicate high usage with colors/classes
        css_class = "normal"
        if total_cpu > 80:
            css_class = "warning"
        if any(p['cpu'] > 90 for p in projects.values()):
            css_class = "critical"
            
        out = {
            "text": text,
            "tooltip": tooltip,
            "class": css_class
        }
        
        print(json.dumps(out), flush=True)
        time.sleep(2)

if __name__ == '__main__':
    main()
