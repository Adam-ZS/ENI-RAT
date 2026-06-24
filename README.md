# ENI-RAT

**Remote Administration Toolkit — Command & Control Framework**

A complete C2 framework designed for red team operations, security assessments, and authorized penetration testing. End-to-end AES-256 encryption, self-hosted dynamic DNS, cross-platform agents, and a browser-based control panel.

```
This tool is for authorized security testing and educational purposes only.
Unauthorized access to computer systems is illegal. You are responsible
for complying with all applicable laws.
```

---

## What It Does

ENI-RAT gives you full remote control over target systems through an encrypted tunnel. The architecture is split into two parts — a C2 server that you run on your machine, and a lightweight agent that runs on the target. The agent phones home, and you control everything from a web dashboard or desktop GUI.

**Core capabilities:**

- Full shell access — execute any system command on the target
- Keylogging — captures keystrokes per active window
- Screen capture — takes screenshots of the target desktop
- File exfiltration — pull files from the target or push files to it
- Persistence — survives reboots via registry, scheduled tasks, crontab, or systemd
- Self-destruct — removes all traces and deletes itself from the target

**Evasion features (Windows):**

- AMSI patching — bypasses PowerShell and in-memory scanning
- ETW patching — disables Windows Event Tracing
- Windows Defender suppression — disables real-time monitoring, cloud-delivered protection, and all scanning subsystems
- AV process termination — kills known antivirus processes automatically
- Sandbox detection — detects VMs, debuggers, and analysis environments, and stays dormant if it finds one
- Encrypted communications — all traffic is AES-256-CBC encrypted

**Custom infrastructure:**

- Self-hosted DDNS — agents register themselves with a hostname so you don't need a static IP or a third-party DDNS service
- Agents are reachable by hostname through your own C2 server
- No dependency on No-IP, DuckDNS, or any external service

---

## Quick Start

### Requirements

```bash
pip install -r requirements.txt
```

### Start the C2 Server

```bash
python3 start.py
```

This starts two services on your machine:
- A WebSocket server on port 8443 (agent communications)
- A REST API and web dashboard on port 5000

Open `http://localhost:5000` in a browser to see the control panel.

### Build a Payload

```bash
python3 builder/builder.py --host YOUR_IP_ADDRESS
```

The builder takes your C2 server's IP or hostname and embeds it into the agent payload along with a unique AES-256 key pair. The output is a Python script that, when run on the target, connects back to your C2.

**Builder options:**

| Flag | Description |
|---|---|
| `--host` | C2 server IP or hostname (required) |
| `--ws-port` | WebSocket port (default: 8443) |
| `--api-port` | REST API port (default: 5000) |
| `--compile` | Compile to a Windows executable via PyInstaller |
| `--obfuscate` | Obfuscate with PyArmor |
| `--no-persistence` | Exclude persistence mechanisms |
| `--no-sandbox-check` | Exclude sandbox/VM detection |

---

## Architecture

```
  TARGET MACHINE                   YOUR MACHINE
  ┌─────────────────┐             ┌──────────────────────┐
  │   Agent          │             │   C2 Server          │
  │   (payload.py)   │◄──AES-256──│                      │
  │                  │  WebSocket  │  WebSocket :8443     │
  │  • Keylogger     │             │  REST API  :5000     │
  │  • Screenshot    │             │  SQLite Database     │
  │  • Shell         │             │  Custom DDNS         │
  │  • File ops      │             │                      │
  │  • Persistence   │             └──────────┬───────────┘
  │  • AV evasion    │                        │
  └─────────────────┘              ┌──────────┴───────────┐
                                   │  Control Interface   │
                                   │                      │
                                   │  Web Dashboard       │
                                   │  Desktop GUI          │
                                   │  Command Line        │
                                   └──────────────────────┘
```

---

## Agent Commands

Once an agent checks in, you can send it commands through the C2 interface.

| Command | What It Does |
|---|---|
| `shell <command>` | Execute a shell command on the target |
| `screenshot` | Capture the target's screen and return the image |
| `keylog_start` | Begin capturing keystrokes |
| `keylog_stop` | Stop the keylogger and retrieve captured data |
| `upload <path>` | Read a file from the target and exfiltrate it to the C2 |
| `download <url> <path>` | Download a file from a URL and save it to the target |
| `persist` | Install persistence on the target |
| `kill_av` | Attempt to terminate antivirus processes |
| `info` | Return system information (OS, hostname, user, IPs) |
| `sleep <seconds>` | Pause the agent for a specified duration |
| `exit` | Tell the agent to terminate |
| `selfdestruct` | Remove all traces, persistence mechanisms, and delete the agent binary |

---

## Custom DDNS

ENI-RAT includes its own dynamic DNS system so you don't need a static IP or a third-party service like No-IP.

When an agent connects, it registers itself with a hostname in the format `hostname-username`. You can then resolve any agent's current IP through the C2 API at any time without needing to check logs or remember addresses.

This is useful when:
- Your C2 server is on a dynamic IP
- You have multiple agents and need to track them by name
- You want to avoid third-party DNS services that could log your activity

---

## Project Structure

```
├── server/
│   ├── c2_core.py          WebSocket C2 server and agent communication handler
│   └── api_server.py       REST API and browser-based web dashboard
├── client/
│   └── payload.py          Cross-platform agent (Windows and Linux)
├── gui/
│   └── rat_gui.py          Desktop GUI built with CustomTkinter
├── builder/
│   ├── builder.py          Payload builder with configuration injection
│   └── update_ddns.sh      DDNS update script for the C2 server
├── start.py                Launches both C2 server and API server
├── requirements.txt        Python dependencies
└── README.md
```

---

## Encryption

All agent-to-C2 communications are encrypted with AES-256 in CBC mode. Each build generates a unique 32-byte key and 16-byte initialization vector. These are embedded in the agent payload during the build process and never transmitted over the network.

---

## Requirements

- Python 3.8 or later
- Linux or Windows for the C2 server
- Windows or Linux for agents
- Dependencies listed in requirements.txt

---

## License and Disclaimer

This software is provided for authorized security testing, research, and educational purposes. Unauthorized access to computer systems is illegal. The authors assume no liability and are not responsible for any misuse or damage caused by this program.

By using this software, you agree that you are solely responsible for complying with all applicable local, state, national, and international laws.

---

Built for red team operations.
