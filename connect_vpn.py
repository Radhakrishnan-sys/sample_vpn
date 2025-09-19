import subprocess
import os
import platform
import time
import webbrowser
from dotenv import load_dotenv

def connect_vpn():
    """
    Connects to an OpenVPN server using a configuration file and credentials from a .env file.
    """
    # Load environment variables from .env file
    load_dotenv()
    
    # Get configuration and credentials from environment variables
    vpn_config = os.getenv("VPN_CONFIG_FILE")
    username = os.getenv("VPN_USERNAME")
    password = os.getenv("VPN_PASSWORD")
    startup_url = os.getenv("STARTUP_URL") # Get the URL to open from .env file

    if not vpn_config or not username or not password or not startup_url:
        print("Error: Missing required variables in the .env file. Please check VPN_CONFIG_FILE, VPN_USERNAME, VPN_PASSWORD, and STARTUP_URL.")
        return

    # Create a temporary file to pass credentials securely
    temp_creds_file_name = "temp_creds.txt"
    with open(temp_creds_file_name, 'w') as temp_f:
        temp_f.write(f"{username}\n{password}\n")

    # Determine the command based on the operating system
    system = platform.system()
    
    if system == 'Windows':
        openvpn_command = "openvpn.exe"
        command = [openvpn_command, '--config', vpn_config, '--auth-user-pass', temp_creds_file_name]
    
    elif system == 'Linux':
        openvpn_command = "openvpn"
        command = ['sudo', openvpn_command, '--config', vpn_config, '--auth-user-pass', temp_creds_file_name]
    
    else:
        print(f"Unsupported operating system: {system}")
        os.remove(temp_creds_file_name)
        return

    print("Attempting to connect to VPN...")
    try:
        process = subprocess.Popen(command)
        
        time.sleep(10)
        
        if process.poll() is None:
            print("VPN connection initiated successfully.")
            open_browser(startup_url) # Call the function to open the browser
        else:
            print("VPN connection failed. Please check your configuration and credentials.")

    except FileNotFoundError:
        print("Error: OpenVPN command not found. Make sure OpenVPN is installed and in your system's PATH.")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
    finally:
        if os.path.exists(temp_creds_file_name):
            os.remove(temp_creds_file_name)

def open_browser(url):
    """
    Opens the specified URL in the user's default web browser.
    """
    print(f"Opening browser and navigating to {url}...")
    try:
        webbrowser.open_new_tab(url)
    except Exception as e:
        print(f"Error opening browser: {e}")

if __name__ == "__main__":
    connect_vpn()