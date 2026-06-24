# ⚡ ENI-RAT

**Remote Administration Toolkit — Red Team C2 Framework**

A full-featured command and control framework for remote system administration, security assessments, and red team operations. AES-256 encrypted communications, self-hosted dynamic DNS, cross-platform agents, and a modern dark-themed web panel.

> **Disclaimer:** This tool is for authorized security testing and educational purposes only. Unauthorized access to computer systems is illegal. Use responsibly.

---

## ✨ Features

### 🖥️ C2 Server
- **WebSocket** based real-time communication with AES-256-CBC encryption
- **REST API** for web panel and third-party integrations
- **SQLite** database — lightweight, portable, zero config
- **Self-hosted DDNS** — replaces No-IP/DuckDNS, agents auto-register with hostnames

### 🎯 Agents (Windows & Linux)
- **Full shell access** — execute any command on target
- **Keylogger** — captures keystrokes per active window
- **Screenshot capture** — real-time screen grabs
- **File exfiltration** — upload/download any file
- **Persistence** — registry + scheduled tasks (Windows), crontab + systemd (Linux)
- **Self-destruct** — wipes all traces and removes itself
- **Sandbox detection** — detects VMs, debuggers, and analysis environments

### 🛡️ AV Evasion (Windows)
- **AMSI patching** — bypasses PowerShell/Memory scanning
- **ETW patching** — disables Event Tracing for Windows
- **Defender suppression** — disables real-time monitoring, cloud protection, and scanning features
- **Process killer** — terminates known AV processes

### 🎮 User Interfaces
- **Web Dashboard** — dark hacker-themed control panel, accessible from any browser
- **Desktop GUI** — CustomTkinter native app with real-time agent monitoring and command console
- **CLI** — terminal-based C2 server with runtime commands

### 🌐 Custom DDNS
- Agents register as `hostname-user.en1` automatically
- No third-party services — fully self-hosted
- Resolve any agent's IP through the C2 API
- Perfect for dynamic IP environments

---

## 🚀 Quick Start

### Prerequisites
```bash
pip install -r requirements.txt
```

### Start the C2
```bash
python3 start.py
```

This launches both:
- WebSocket server on `ws://0.0.0.0:8443`
- Web panel on `http://0.0.0.0:5000`

### Build a Payload
```bash
python3 builder/builder.py --host YOUR_C2_IP
```

Options:
```
--host          C2 server IP or hostname (required)
--ws-port       WebSocket port (default: 8443)
--api-port      API port (default: 5000)
--compile       Compile to EXE (requires PyInstaller on Windows)
--obfuscate     Apply PyArmor obfuscation
--no-persistence    Disable persistence installation
--no-sandbox-check  Disable VM/sandbox detection
```

---

## 📂 Project Structure

```
├── server/
│   ├── c2_core.py          # WebSocket C2 server
│   └── api_server.py       # REST API + web dashboard
├── client/
│   └── payload.py          # Cross-platform agent
├── gui/
│   └── rat_gui.py          # Desktop GUI (CustomTkinter)
├── builder/
│   ├── builder.py          # Payload builder
│   └── update_ddns.sh      # DDNS updater script
├── start.py                # One-command launcher
└── requirements.txt
```

---

## 🔧 Usage

### Web Panel
Open `http://localhost:5000` in your browser for the full dashboard.

### Desktop GUI
```bash
python3 gui/rat_gui.py
```

### Agent Commands
| Command | Description |
|---------|-------------|
| `shell <cmd>` | Execute a shell command |
| `screenshot` | Capture target screen |
| `keylog_start` | Start keylogger |
| `keylog_stop` | Stop and retrieve keystrokes |
| `upload <path>` | Upload a file from target |
| `download <url> <path>` | Download a file to target |
| `persist` | Install persistence |
| `kill_av` | Terminate AV processes |
| `info` | Get system information |
| `sleep <sec>` | Sleep for N seconds |
| `selfdestruct` | Remove all traces and exit |

---

## 🔒 Encryption

All C2 communications are encrypted with AES-256-CBC:
- Unique 32-byte key and 16-byte IV generated per build
- Keys are embedded in the payload during build
- Each session uses unique encryption parameters

---

## ⚙️ Architecture

```
┌──────────────┐    AES-256     ┌──────────────────┐
│   Target     │ ◄──────────►   │   C2 Server      │
│  (Agent)     │   WebSocket    │  (Your Machine)   │
│              │                │                   │
│ • Keylogger  │                │ • WebSocket :8443 │
│ • Screenshot │                │ • REST API  :5000 │
│ • Shell      │                │ • SQLite Database │
│ • Exfiltrate │                │ • Custom DDNS     │
└──────────────┘                └──────────────────┘
                                        │
                                        ▼
                               ┌──────────────────┐
                               │  Web Panel/GUI   │
                               │  (Browser/App)   │
                               └──────────────────┘
```

---

## 📋 Requirements

- Python 3.8+
- Linux/Windows for C2 server
- Windows/Linux for agents
- Dependencies listed in `requirements.txt`

## 📝 License

For authorized security testing and educational purposes only.

---

*Built with ❤️ for red team operations*
