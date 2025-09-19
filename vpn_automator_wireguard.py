#!/usr/bin/env python3
"""
vpn_automator_wireguard_pm.py

Hybrid automation for WireGuard using package managers:
 - Linux: installs WireGuard via apt-get or dnf
 - Windows: installs WireGuard via winget or choco
 - Connection: runs wg-quick up (Linux/macOS) or instructs manual start (Windows)

Author: GEN AI Scientist (20+ years experience)
"""

import os
import sys
import platform
import shutil
import subprocess
from pathlib import Path
from dotenv import load_dotenv

# ---------- Utilities ----------

def fatal(msg: str, code: int = 1):
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(code)

def info(msg: str):
    print(f"[INFO] {msg}")

def warn(msg: str):
    print(f"[WARN] {msg}")

def run_command(cmd, shell=False):
    info("Running: " + " ".join(cmd) if not shell else str(cmd))
    try:
        subprocess.run(cmd, check=True, shell=shell)
    except subprocess.CalledProcessError as e:
        fatal(f"Command failed with exit code {e.returncode}: {e}")

# ---------- Env config ----------

def load_configuration() -> dict:
    load_dotenv()
    cfg = {
        "WG_CONFIG_FILE": os.getenv("WG_CONFIG_FILE", "").strip(),
        "WG_INTERFACE_NAME": os.getenv("WG_INTERFACE_NAME", "wg0").strip(),
    }
    return cfg

def sanity_check_config(cfg: dict) -> None:
    if not cfg["WG_CONFIG_FILE"]:
        fatal("Missing required env var: WG_CONFIG_FILE")

# ---------- Dependency checks ----------

def check_wireguard_present() -> bool:
    system = platform.system().lower()
    if system.startswith("win"):
        return shutil.which("wireguard.exe") or shutil.which("wg.exe") or shutil.which("wg-quick.exe")
    else:
        return shutil.which("wg-quick") or shutil.which("wg")

# ---------- Installation ----------

def install_wireguard_linux():
    if shutil.which("apt-get"):
        run_command(["sudo", "apt-get", "update"])
        run_command(["sudo", "apt-get", "install", "-y", "wireguard", "wireguard-tools"])
    elif shutil.which("dnf"):
        run_command(["sudo", "dnf", "install", "-y", "wireguard-tools"])
    else:
        fatal("Unsupported Linux distro: neither apt-get nor dnf found.")

def install_wireguard_windows():
    if shutil.which("winget"):
        run_command(["winget", "install", "--id", "WireGuard.WireGuard", "-e", "--silent"], shell=True)
    elif shutil.which("choco"):
        run_command(["choco", "install", "wireguard", "-y"], shell=True)
    else:
        fatal("Neither winget nor choco found. Install WireGuard manually.")

def install_wireguard():
    system = platform.system().lower()
    if system.startswith("linux"):
        install_wireguard_linux()
    elif system.startswith("win"):
        install_wireguard_windows()
    elif system.startswith("darwin"):
        warn("On macOS, please install via Homebrew: brew install wireguard-tools")
    else:
        fatal("Unsupported OS for automatic installation.")

# ---------- Connection ----------

def connect_wireguard(cfg: dict):
    wg_conf = Path(cfg["WG_CONFIG_FILE"])
    if not wg_conf.exists():
        fatal(f"WireGuard config not found: {wg_conf}")

    system = platform.system().lower()
    if system.startswith("linux") or system.startswith("darwin"):
        cmd = ["wg-quick", "up", str(wg_conf)]
        try:
            if os.geteuid() != 0:
                cmd = ["sudo"] + cmd
        except AttributeError:
            pass
        run_command(cmd)
        info("Tunnel is now active. To disconnect: sudo wg-quick down " + str(wg_conf))
    elif system.startswith("win"):
        info("On Windows, WireGuard GUI usually manages tunnels.")
        info("Please import your .conf file into the WireGuard app and activate manually.")
        input("Press Enter once the tunnel is active to continue...")
    else:
        fatal("Unsupported OS for WireGuard connection.")

# ---------- Main ----------

def main():
    cfg = load_configuration()
    sanity_check_config(cfg)

    if not check_wireguard_present():
        info("WireGuard not found, installing...")
        install_wireguard()
        if not check_wireguard_present():
            fatal("WireGuard installation failed or binary not in PATH.")

    connect_wireguard(cfg)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[ABORTED]")
        sys.exit(2)
