#!/usr/bin/env python3
"""
vpn_automator.py

Hybrid automation:
 - Web automation via Selenium to download OpenVPN client installer (Windows or Linux)
 - System-level automation via subprocess to run openvpn with provided credentials

Strict design constraints:
 - Uses .env for all secrets/config
 - Uses webdriver-manager to fetch appropriate driver
 - Does NOT bypass OS installer security prompts; requests user to run installer manually
 - Works on Linux and Windows (best-effort)
"""

import os
import sys
import platform
import shutil
import tempfile
import subprocess
from pathlib import Path
from typing import Optional, Tuple
from dotenv import load_dotenv

# ---------- Constants ----------
REQUIRED_PY_LIBS = ("selenium", "webdriver_manager", "python_dotenv")
DEFAULT_DOWNLOAD_TIMEOUT = 120  # seconds

# ---------- Utility functions ----------

def fatal(msg: str, code: int = 1):
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(code)

def info(msg: str):
    print(f"[INFO] {msg}")

def warn(msg: str):
    print(f"[WARN] {msg}")

# ---------- Dependency checks ----------

def check_python_dependencies() -> None:
    """Ensure required Python libraries are importable. If not, instruct user to pip install."""
    missing = []
    try:
        import selenium  # noqa: F401
    except Exception:
        missing.append("selenium")
    try:
        import webdriver_manager  # noqa: F401
    except Exception:
        missing.append("webdriver-manager")
    try:
        import dotenv  # noqa: F401
    except Exception:
        missing.append("python-dotenv")

    if missing:
        print()
        warn("Missing Python packages: " + ", ".join(missing))
        print("Please install them manually (example):")
        print("  pip install selenium webdriver-manager python-dotenv")
        fatal("Missing dependencies. Aborting.")

def find_executable(cmd: str) -> Optional[str]:
    """Return absolute path of executable if found in PATH, else None."""
    return shutil.which(cmd)

# ---------- Environment loading ----------

def load_configuration(env_path: Optional[str] = None) -> dict:
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()  # load .env from cwd by default

    cfg = {
        "DOWNLOAD_PAGE_URL": os.getenv("DOWNLOAD_PAGE_URL", "").strip(),
        "VPN_CONFIG_FILE": os.getenv("VPN_CONFIG_FILE", "").strip(),
        "VPN_USERNAME": os.getenv("VPN_USERNAME", "").strip(),
        "VPN_PASSWORD": os.getenv("VPN_PASSWORD", "").strip(),
        "BROWSER": os.getenv("BROWSER", "").strip().lower() or None,
        "DOWNLOAD_TIMEOUT": int(os.getenv("DOWNLOAD_TIMEOUT") or DEFAULT_DOWNLOAD_TIMEOUT)
    }
    return cfg

def sanity_check_config(cfg: dict) -> None:
    missing = []
    if not cfg["DOWNLOAD_PAGE_URL"]:
        missing.append("DOWNLOAD_PAGE_URL")
    if not cfg["VPN_CONFIG_FILE"]:
        missing.append("VPN_CONFIG_FILE")
    if not cfg["VPN_USERNAME"]:
        missing.append("VPN_USERNAME")
    if not cfg["VPN_PASSWORD"]:
        missing.append("VPN_PASSWORD")
    if missing:
        fatal("Missing required environment variables: " + ", ".join(missing))

# ---------- Selenium download logic ----------

def choose_browser_preference(cfg_browser: Optional[str]) -> str:
    """Choose chrome or firefox based on availability and preference."""
    if cfg_browser:
        if cfg_browser in ("chrome", "firefox"):
            return cfg_browser
        else:
            warn(f"Unknown BROWSER='{cfg_browser}' in .env — defaulting to auto")
    # default preference: chrome
    return "chrome"

def prepare_webdriver(download_dir: str, prefer_browser: str):
    """
    Create and return a Selenium WebDriver instance configured to download files automatically.
    Uses webdriver-manager to install driver.
    """
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from webdriver_manager.chrome import ChromeDriverManager
    from webdriver_manager.firefox import GeckoDriverManager

    # Attempt Chrome first (preferred)
    if prefer_browser == "chrome":
        try:
            opts = ChromeOptions()
            # Headed mode to allow interactions (downloads, explicit waits)
            prefs = {
                "download.default_directory": download_dir,
                "download.prompt_for_download": False,
                "profile.default_content_settings.popups": 0
            }
            opts.add_experimental_option("prefs", prefs)
            # disable automation infobar (non-essential)
            opts.add_experimental_option("excludeSwitches", ["enable-automation"])
            # create driver
            driver = webdriver.Chrome(ChromeDriverManager().install(), options=opts)
            info("Using Chrome WebDriver")
            return driver, "chrome"
        except Exception as e:
            warn(f"Chrome driver init failed: {e}. Falling back to Firefox.")

    # Try Firefox
    try:
        opts = FirefoxOptions()
        profile = webdriver.FirefoxProfile()
        profile.set_preference("browser.download.folderList", 2)
        profile.set_preference("browser.download.dir", download_dir)
        profile.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/octet-stream,application/x-debian-package,application/x-rpm,application/x-msdos-program,application/x-msdownload")
        driver = webdriver.Firefox(executable_path=GeckoDriverManager().install(), firefox_profile=profile, options=opts)
        info("Using Firefox WebDriver")
        return driver, "firefox"
    except Exception as e:
        warn(f"Firefox driver init failed: {e}")

    fatal("Could not instantiate a Selenium WebDriver. Ensure webdriver-manager can download drivers and you have network access.")

def find_and_click_download(driver, cfg_url: str, target_os: str, timeout: int = 60) -> Tuple[Optional[str], Optional[str]]:
    """
    Navigate to cfg_url and try to find a download link appropriate for target_os.
    Strategies:
      1. Search for anchor tags whose href ends with known installer suffixes
      2. Search by visible text that includes the OS name
    Returns (download_href, filename) or (None, None) on failure.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import urllib.parse as up

    info(f"Navigating to download page: {cfg_url}")
    driver.get(cfg_url)

    wait = WebDriverWait(driver, timeout)
    # Wait for some <a> elements to appear — page-specific; we use presence_of_all_elements_located as a baseline
    try:
        wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "a")))
    except Exception:
        warn("No anchor tags found on page — the page may be javascript heavy or blocked. Continuing with best-effort parsing.")

    # Candidate file suffixes and text keywords
    suffixes = {
        "windows": [".exe", ".msi"],
        "linux": [".deb", ".rpm", ".tar.gz", ".tar.xz"]
    }
    keywords = {
        "windows": ["windows", "msi", "exe", "Windows"],
        "linux": ["linux", ".deb", ".rpm", "Linux"]
    }

    anchors = driver.find_elements(By.TAG_NAME, "a")
    candidates = []
    for a in anchors:
        try:
            href = a.get_attribute("href") or ""
            text = (a.text or "").strip()
            # consider data-href, onclick navigation, etc.
            if not href:
                # attempt to inspect onclick (best-effort)
                onclick = a.get_attribute("onclick") or ""
                if "http" in onclick:
                    # extract first http... substring
                    import re
                    match = re.search(r"(https?://[^\']+)", onclick)
                    if match:
                        href = match.group(1)
            if href:
                lower = href.lower()
                for suf in suffixes.get(target_os, []):
                    if lower.endswith(suf):
                        candidates.append((href, a, text))
                # sometimes href doesn't end with suffix but contains keywords
                for kw in keywords.get(target_os, []):
                    if kw.lower() in lower or kw in text:
                        candidates.append((href, a, text))
        except Exception:
            continue

    # deduplicate by href, prefer exact suffix matches
    unique = {}
    for href, a, text in candidates:
        key = href.split("#")[0]
        unique.setdefault(key, []).append((href, text))
    hrefs = list(unique.keys())

    if not hrefs:
        warn("No obvious installer link found automatically. The website may require manual download or selectors need updating.")
        return None, None

    # Prefer exact suffix matches first
    for key in hrefs:
        for suf in suffixes.get(target_os, []):
            if key.lower().endswith(suf):
                chosen = key
                info(f"Selected download link (by suffix): {chosen}")
                try:
                    driver.execute_script("arguments[0].click();", driver.find_element(By.XPATH, f"//a[@href='{chosen}']"))
                except Exception:
                    # fallback: find element with href containing chosen
                    try:
                        el = driver.find_element(By.XPATH, f"//a[contains(@href, '{chosen}')]")
                        driver.execute_script("arguments[0].click();", el)
                    except Exception:
                        warn("Could not click download anchor via Selenium script; will attempt to navigate directly to href.")
                        driver.get(chosen)
                return chosen, Path(up.urlparse(chosen).path).name or None

    # fallback to first candidate
    chosen = hrefs[0]
    info(f"Selected download link (fallback): {chosen}")
    try:
        driver.execute_script("arguments[0].click();", driver.find_element(By.XPATH, f"//a[@href='{chosen}']"))
    except Exception:
        try:
            el = driver.find_element(By.XPATH, f"//a[contains(@href, '{chosen}')]")
            driver.execute_script("arguments[0].click();", el)
        except Exception:
            driver.get(chosen)
    return chosen, Path(up.urlparse(chosen).path).name or None

def wait_for_download_completion(download_dir: Path, partial_exts=(".crdownload", ".part", ".partial", ".download"), timeout: int = DEFAULT_DOWNLOAD_TIMEOUT):
    """
    Wait until a new non-partial file appears in download_dir or until timeout.
    Returns the Path to the downloaded file or None on timeout.
    """
    import time
    start = time.time()
    existing = set(p.name for p in download_dir.iterdir())
    info(f"Existing files before download: {existing}")
    while time.time() - start < timeout:
        current_files = list(download_dir.iterdir())
        # find new files
        new = [p for p in current_files if p.name not in existing]
        # filter out temporary partial files
        completed = []
        for p in new:
            if any(str(p).endswith(ext) for ext in partial_exts):
                # still downloading
                continue
            # if file exists and size is stable across small window, consider complete
            try:
                size1 = p.stat().st_size
                # quick stable-check
                import time as _t
                _t.sleep(0.5)
                size2 = p.stat().st_size
            except Exception:
                continue
            if size1 == size2 and size1 > 0:
                completed.append(p)
        if completed:
            info(f"Detected completed download: {[str(x) for x in completed]}")
            # pick the largest (likely the installer)
            completed.sort(key=lambda p: p.stat().st_size, reverse=True)
            return completed[0]
        # also check for files without being 'new' in case driver put same name
        for p in current_files:
            if p.name in existing:
                # check if it was previously partial and now complete
                if not any(p.name.endswith(ext) for ext in partial_exts):
                    try:
                        if p.stat().st_size > 0:
                            return p
                    except Exception:
                        pass
        import time as _t
        _t.sleep(1)
    warn("Timeout waiting for download completion.")
    return None

def download_installer(cfg: dict) -> Path:
    """Orchestrate Selenium to download the OS-appropriate installer and return the downloaded file path."""
    # choose OS
    system = platform.system().lower()
    target_os = "windows" if system.startswith("win") else "linux"
    info(f"Detected OS: {system} -> target_os={target_os}")

    # prepare temporary download folder
    tmp = Path(tempfile.mkdtemp(prefix="vpn_download_"))
    info(f"Using temporary download dir: {tmp}")

    prefer = choose_browser_preference(cfg.get("BROWSER"))
    driver, browser_used = prepare_webdriver(str(tmp), prefer)

    try:
        href, filename = find_and_click_download(driver, cfg["DOWNLOAD_PAGE_URL"], target_os, timeout=30)
        if not href:
            driver.quit()
            fatal("Could not find a suitable download link on the page. Please download installer manually and place in the same folder as this script or update page selectors.")
        info("Download initiated, waiting for the file to appear in download folder...")
        downloaded = wait_for_download_completion(tmp, timeout=cfg.get("DOWNLOAD_TIMEOUT", DEFAULT_DOWNLOAD_TIMEOUT))
        driver.quit()
        if not downloaded:
            fatal("Download did not complete within timeout. Please check network, browser prompts, or download page.")
        info(f"Downloaded file located at: {downloaded}")
        return downloaded
    finally:
        try:
            driver.quit()
        except Exception:
            pass

# ---------- Installer handoff (manual) ----------

def ask_user_to_run_installer(installer_path: Path) -> None:
    """
    Provide instructions to the user on how to run the installer with admin rights.
    Wait for their confirmation to proceed.
    """
    info("ATTENTION: Automated installation of GUI installers is intentionally NOT attempted.")
    info("Please run the downloaded installer manually with administrative privileges.")
    print()
    print("  1) Installer file:", installer_path)
    if platform.system().lower().startswith("win"):
        print("  2) Right click -> Run as administrator")
        print("  3) During installation: check 'Add to PATH' or similar if offered (recommended)")
    else:
        # Linux guesses by extension
        if installer_path.suffix == ".deb":
            print("  2) Run: sudo dpkg -i \"{}\" && sudo apt-get -f install -y".format(installer_path))
        elif installer_path.suffix == ".rpm":
            print("  2) Run: sudo rpm -ivh \"{}\"".format(installer_path))
        elif installer_path.suffix in (".tar.gz", ".tar.xz"):
            print("  2) Extract and follow included README / install instructions")
        else:
            print("  2) Run installer according to your distro's guidelines with root privileges")
    print()
    print("After you have completed installation, please confirm (type 'yes') so the script will continue to the connection step.")
    while True:
        choice = input("Have you completed installation? (yes/no): ").strip().lower()
        if choice == "yes":
            return
        elif choice in ("no", "n"):
            print("Please complete installation and return here when finished.")
        else:
            print("Please type 'yes' when installation is complete, or ctrl-c to abort.")

# ---------- VPN connection logic ----------

def check_openvpn_present() -> Optional[str]:
    """Check if openvpn binary is available. On Windows, commonly 'openvpn.exe'."""
    candidates = ["openvpn"]
    if platform.system().lower().startswith("win"):
        candidates = ["openvpn.exe", "openvpn"]
    for c in candidates:
        p = find_executable(c)
        if p:
            return p
    return None

def create_auth_file(username: str, password: str, parent_dir: Optional[Path] = None) -> Path:
    """Create a temporary file with username and password in two lines suitable for --auth-user-pass"""
    parent = parent_dir or Path(tempfile.mkdtemp(prefix="vpn_auth_"))
    parent.mkdir(parents=True, exist_ok=True)
    authf = parent / "openvpn_auth.txt"
    authf.write_text(username + "\n" + password + "\n")
    # restrict permissions on POSIX
    try:
        if os.name == "posix":
            authf.chmod(0o600)
    except Exception:
        pass
    return authf

def connect_vpn(cfg: dict) -> None:
    """
    Execute openvpn with --config and --auth-user-pass to connect.
    For Linux: will prefix with sudo if not root.
    """
    openvpn_path = check_openvpn_present()
    if not openvpn_path:
        fatal("openvpn executable not found in PATH. Ensure installer added openvpn to PATH or run it manually. Aborting.")

    ovpn = Path(cfg["VPN_CONFIG_FILE"])
    if not ovpn.exists():
        fatal(f"VPN config file not found: {ovpn}")

    auth_file = create_auth_file(cfg["VPN_USERNAME"], cfg["VPN_PASSWORD"])

    cmd = [openvpn_path, "--config", str(ovpn), "--auth-user-pass", str(auth_file)]

    # On Linux, if not root, prefix with sudo to allow creating TUN devices
    if platform.system().lower().startswith("linux"):
        if os.geteuid() != 0:
            cmd = ["sudo"] + cmd

    info("Launching OpenVPN process. You will likely be asked for sudo password (on Linux) or admin rights (on Windows).")
    info("Command: " + " ".join(cmd))
    # We will run in a subprocess and stream output to the console
    try:
        # Use Popen so user can ctrl-c to stop
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    except Exception as e:
        fatal(f"Failed to start openvpn process: {e}")

    # stream output lines
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            print(line, end="")
    except KeyboardInterrupt:
        warn("User requested termination (KeyboardInterrupt). Terminating OpenVPN process...")
        proc.terminate()
        proc.wait(timeout=5)
    except Exception as e:
        warn(f"Error while reading OpenVPN output: {e}")
    finally:
        if proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        info("OpenVPN process ended.")

# ---------- Main orchestration ----------

def main():
    # 1. dependency check (python libs)
    check_python_dependencies()

    # 2. load config
    cfg = load_configuration()
    sanity_check_config(cfg)

    # 3. Check if openvpn is already installed
    if check_openvpn_present():
        info("openvpn found in PATH. Skipping download/installer step.")
        installed = True
    else:
        installed = False

    installer_path = None
    if not installed:
        # 4. Web automation -> download installer
        try:
            installer_path = download_installer(cfg)
        except Exception as e:
            fatal(f"Download step failed: {e}")

        # 5. Tell user to run installer manually
        ask_user_to_run_installer(installer_path)

        # After user confirms, re-check openvpn
        if not check_openvpn_present():
            warn("openvpn still not found in PATH after you confirmed installation.")
            warn("If installer installs OpenVPN but did not add it to PATH, locate openvpn binary and add to PATH or rerun script.")
            # give user opportunity to proceed anyway (maybe they will provide path)
            choice = input("Do you want to attempt to continue anyway? (yes/no): ").strip().lower()
            if choice != "yes":
                fatal("Aborting as openvpn is not available.")
        info("Proceeding to connection step.")

    # 6. Connect to VPN
    try:
        connect_vpn(cfg)
    except Exception as e:
        fatal(f"Connection step failed: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[ABORTED] User interrupted.")
        sys.exit(2)
