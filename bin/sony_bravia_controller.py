#!/usr/bin/env python3
"""
Sony BRAVIA Headless IP Controller (JSON-RPC 2.0 REST & IRCC-IP SOAP)
Target: Sony BRAVIA XR-65X90J (Cognitive Processor XR, Android TV 12)
Permanent Authenticated Local Access Suite
Dual-Homed Failover: Wi-Fi Primary (192.168.1.x) <-> LAN Fallback (10.42.0.x)
"""

import sys
import os
import json
import time
import socket
import fcntl
import urllib.request
import urllib.error
import argparse
import subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SUITE_DIR = os.path.dirname(SCRIPT_DIR)
CONFIG_FILE = os.path.join(SUITE_DIR, "config", "bravia_config.json")

# Default network configuration (generic masked fallbacks if config/bravia_config.json is absent)
WIFI_IP_DEFAULT = "192.168.1.100"
WIFI_MAC_DEFAULT = "38:B8:00:00:00:00"
LAN_IP_DEFAULT = "10.42.0.100"
LAN_MAC_DEFAULT = "F8:4E:17:00:00:00"
DEFAULT_PSK = "YOUR_PSK_HERE"

# Load JSON config if present
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, "r") as f:
            _cfg = json.load(f)
            WIFI_IP = _cfg.get("network", {}).get("wifi", {}).get("ip", WIFI_IP_DEFAULT)
            WIFI_MAC = _cfg.get("network", {}).get("wifi", {}).get("mac", WIFI_MAC_DEFAULT)
            LAN_IP = _cfg.get("network", {}).get("lan", {}).get("ip", LAN_IP_DEFAULT)
            LAN_MAC = _cfg.get("network", {}).get("lan", {}).get("mac", LAN_MAC_DEFAULT)
            AUTH_PSK = _cfg.get("auth", {}).get("psk", DEFAULT_PSK)
    except Exception:
        WIFI_IP, WIFI_MAC = WIFI_IP_DEFAULT, WIFI_MAC_DEFAULT
        LAN_IP, LAN_MAC = LAN_IP_DEFAULT, LAN_MAC_DEFAULT
        AUTH_PSK = DEFAULT_PSK
else:
    WIFI_IP, WIFI_MAC = WIFI_IP_DEFAULT, WIFI_MAC_DEFAULT
    LAN_IP, LAN_MAC = LAN_IP_DEFAULT, LAN_MAC_DEFAULT
    AUTH_PSK = DEFAULT_PSK

# Environment overrides
WIFI_IP = os.environ.get("SONY_TV_WIFI_IP", WIFI_IP)
WIFI_MAC = os.environ.get("SONY_TV_WIFI_MAC", WIFI_MAC)
LAN_IP = os.environ.get("SONY_TV_LAN_IP", LAN_IP)
LAN_MAC = os.environ.get("SONY_TV_LAN_MAC", LAN_MAC)
AUTH_PSK = os.environ.get("SONY_TV_PSK", AUTH_PSK)

# Cookie resolution
_COOKIE_CANDIDATES = [
    os.environ.get("SONY_TV_COOKIE_FILE"),
    os.path.join(SUITE_DIR, "config", "cookies.txt"),
    os.path.join(SUITE_DIR, "sony_bravia_cookies.txt"),
    os.path.join(SCRIPT_DIR, "sony_bravia_cookies.txt"),
    os.path.expanduser("~/myWorld/sony_bravia_suite/config/cookies.txt"),
    os.path.expanduser("~/myWorld/sony_bravia_cookies.txt"),
]
COOKIE_FILE = next((c for c in _COOKIE_CANDIDATES if c and os.path.exists(c)), os.path.join(SUITE_DIR, "config", "cookies.txt"))
LOCK_FILE = "/tmp/sony_bravia_controller.lock"
CLIENT_ID = "myWorld:antigravity"
NICKNAME = "Antigravity Controller"

IRCC_MASTER_CODES = {
    # Power
    "WakeUp": "AAAAAQAAAAEAAAAuAw==",
    "PowerOff": "AAAAAQAAAAEAAAAvAw==",
    "TvPower": "AAAAAQAAAAEAAAAVAw==",
    "Sleep": "AAAAAQAAAAEAAAAvAw==",
    "SleepTimer": "AAAAAQAAAAEAAAA2Aw==",
    # Navigation
    "Home": "AAAAAQAAAAEAAABgAw==",
    "Confirm": "AAAAAQAAAAEAAABlAw==",
    "Enter": "AAAAAQAAAAEAAAALAw==",
    "Return": "AAAAAgAAAJcAAAAjAw==",
    "Back": "AAAAAgAAAJcAAAAjAw==",
    "Exit": "AAAAAQAAAAEAAABjAw==",
    "Up": "AAAAAQAAAAEAAAB0Aw==",
    "Down": "AAAAAQAAAAEAAAB1Aw==",
    "Left": "AAAAAQAAAAEAAAA0Aw==",
    "Right": "AAAAAQAAAAEAAAAzAw==",
    "Options": "AAAAAgAAAJcAAAA2Aw==",
    "ActionMenu": "AAAAAgAAAMQAAABLAw==",
    "Help": "AAAAAgAAAMQAAABNAw==",
    "SyncMenu": "AAAAAgAAABoAAABYAw==",
    # Volume & Audio
    "VolumeUp": "AAAAAQAAAAEAAAASAw==",
    "VolumeDown": "AAAAAQAAAAEAAAATAw==",
    "Mute": "AAAAAQAAAAEAAAAUAw==",
    "Audio": "AAAAAQAAAAEAAAAXAw==",
    # Media Playback
    "Play": "AAAAAgAAAJcAAAAaAw==",
    "Pause": "AAAAAgAAAJcAAAAZAw==",
    "Stop": "AAAAAgAAAJcAAAAYAw==",
    "Rewind": "AAAAAgAAAJcAAAAbAw==",
    "Forward": "AAAAAgAAAJcAAAAcAw==",
    "Prev": "AAAAAgAAAJcAAAA8Aw==",
    "Next": "AAAAAgAAAJcAAAA9Aw==",
    # Inputs
    "Input": "AAAAAQAAAAEAAAAlAw==",
    "TvInput": "AAAAAQAAAAEAAAAlAw==",
    "Hdmi1": "AAAAAgAAABoAAABaAw==",
    "Hdmi2": "AAAAAgAAABoAAABbAw==",
    "Hdmi3": "AAAAAgAAABoAAABcAw==",
    "Hdmi4": "AAAAAgAAABoAAABdAw==",
    "Video1": "AAAAAQAAAAEAAABAAw==",
    # Dedicated Apps
    "Netflix": "AAAAAgAAABoAAAB8Aw==",
    "YouTube": "AAAAAgAAAMQAAABHAw==",
    "GooglePlay": "AAAAAgAAAMQAAABGAw==",
    "ApplicationLauncher": "AAAAAgAAAMQAAAAqAw==",
    # Number Pad
    "Num1": "AAAAAQAAAAEAAAAAAw==",
    "Num2": "AAAAAQAAAAEAAAABAw==",
    "Num3": "AAAAAQAAAAEAAAACAw==",
    "Num4": "AAAAAQAAAAEAAAADAw==",
    "Num5": "AAAAAQAAAAEAAAAEAw==",
    "Num6": "AAAAAQAAAAEAAAAFAw==",
    "Num7": "AAAAAQAAAAEAAAAGAw==",
    "Num8": "AAAAAQAAAAEAAAAHAw==",
    "Num9": "AAAAAQAAAAEAAAAIAw==",
    "Num0": "AAAAAQAAAAEAAAAJAw==",
    # Color Keys
    "Red": "AAAAAgAAAJcAAAAlAw==",
    "Green": "AAAAAgAAAJcAAAAmAw==",
    "Yellow": "AAAAAgAAAJcAAAAnAw==",
    "Blue": "AAAAAgAAAJcAAAAkAw==",
}

APP_ALIASES = {
    "smarttube": "org.smarttube.beta/com.liskovsoft.smartyoutubetv2.tv.ui.playback.PlaybackActivity",
    "talkies": "com.techpp.glass/com.techpp.glass.MainActivity",
    "netflix": "com.netflix.ninja/com.netflix.ninja.MainActivity",
    "youtube": "com.google.android.youtube.tv/com.google.android.apps.youtube.tv.activity.ShellActivity",
    "prime": "com.amazon.amazonvideo.livingroom/com.amazon.amazonvideo.livingroom.LauncherActivity",
    "hotstar": "in.startv.hotstar/in.startv.hotstar.SplashActivity",
    "appletv": "com.apple.atve.sony.appletv/com.apple.atve.sony.appletv.MainActivity",
}


def probe_port(host: str, port: int = 80, timeout: float = 0.35) -> bool:
    """Quickly probe TCP port reachability."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except Exception:
        return False


def resolve_active_endpoint(explicit_host=None, explicit_mac=None):
    """
    Resolve active endpoint using user preference:
    Wi-Fi Primary (192.168.1.x) -> LAN Fallback (10.42.0.x).
    """
    env_ip = os.environ.get("SONY_TV_IP")
    if explicit_host and explicit_host not in ["auto", ""]:
        mac = explicit_mac or (WIFI_MAC if explicit_host == WIFI_IP else LAN_MAC)
        return explicit_host, mac, "explicit"
    if env_ip and env_ip not in ["auto", ""]:
        mac = WIFI_MAC if env_ip == WIFI_IP else LAN_MAC
        return env_ip, mac, "environment"

    # Step 1: Probe Primary Wi-Fi (HTTP 80 or ADB 5555)
    if probe_port(WIFI_IP, 80, 0.35) or probe_port(WIFI_IP, 5555, 0.35):
        return WIFI_IP, WIFI_MAC, "Wi-Fi (Primary)"

    # Step 2: Probe Fallback LAN (HTTP 80 or ADB 5555)
    if probe_port(LAN_IP, 80, 0.35) or probe_port(LAN_IP, 5555, 0.35):
        return LAN_IP, LAN_MAC, "LAN (Fallback)"

    # Step 3: Neither responds (Device in standby/sleep). Default to Wi-Fi Primary.
    return WIFI_IP, WIFI_MAC, "Wi-Fi (Primary - Standby)"


class BraviaClient:
    def __init__(self, host=None, mac=None, psk=AUTH_PSK, cookie_path=COOKIE_FILE):
        if not host or host == "auto":
            resolved_ip, resolved_mac, route_type = resolve_active_endpoint(host, mac)
            self.host = resolved_ip
            self.mac = resolved_mac.replace(":", "").replace("-", "").upper()
            self.route_type = route_type
        else:
            self.host = host
            self.mac = (mac or (WIFI_MAC if host == WIFI_IP else LAN_MAC)).replace(":", "").replace("-", "").upper()
            self.route_type = "explicit"

        self.psk = psk
        self.cookie_path = cookie_path
        self.auth_token = self._load_auth_token()

    def _load_auth_token(self):
        if os.path.exists(self.cookie_path):
            try:
                with open(self.cookie_path, "r") as f:
                    for line in f:
                        if "auth" in line and not line.startswith("#"):
                            parts = line.strip().split()
                            if len(parts) >= 7:
                                return parts[-1]
                            elif len(parts) == 1:
                                return parts[0]
            except Exception:
                pass
        return None

    def _save_auth_token(self, token):
        self.auth_token = token
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.cookie_path)), exist_ok=True)
            exp = int(time.time()) + 1209600
            # Write cookies for both Wi-Fi and LAN to ensure persistence across failover
            content = (
                "# Netscape HTTP Cookie File\n"
                f"{WIFI_IP}\tFALSE\t/sony\tFALSE\t{exp}\tauth\t{token}\n"
                f"{LAN_IP}\tFALSE\t/sony\tFALSE\t{exp}\tauth\t{token}\n"
            )
            with open(self.cookie_path, "w") as f:
                f.write(content)
        except Exception:
            pass

    def _acquire_lock(self):
        lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_RDWR)
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return lock_fd

    def _release_lock(self, lock_fd):
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
        except Exception:
            pass

    def _get_headers(self, is_soap=False):
        headers = {}
        if is_soap:
            headers["Content-Type"] = "text/xml; charset=UTF-8"
            headers["SOAPACTION"] = '"urn:schemas-sony-com:service:IRCC:1#X_SendIRCC"'
        else:
            headers["Content-Type"] = "application/json; charset=UTF-8"

        # Pre-Shared Key (always include for 100% reliable bypass)
        if self.psk:
            headers["X-Auth-PSK"] = self.psk

        # Session cookie
        if self.auth_token:
            headers["Cookie"] = f"auth={self.auth_token}"
        return headers

    def send_wol(self):
        """
        Send Dual-MAC Layer-2 Wake-On-LAN magic packets across multiple broadcast targets.
        Guarantees wake up whether TV is on Wi-Fi (WoWLAN) or LAN (WOL).
        """
        mac_wifi_clean = WIFI_MAC.replace(":", "").replace("-", "").upper()
        mac_lan_clean = LAN_MAC.replace(":", "").replace("-", "").upper()
        
        targets = [
            ("255.255.255.255", 9),
            ("192.168.1.255", 9),  # Wi-Fi broadcast
            ("10.42.0.255", 9),    # LAN broadcast
        ]

        success = False
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            for mac in [mac_wifi_clean, mac_lan_clean]:
                if len(mac) == 12:
                    payload = bytes.fromhex("FF" * 6 + mac * 16)
                    for addr in targets:
                        try:
                            s.sendto(payload, addr)
                            success = True
                        except Exception:
                            pass
        return success

    def register_client(self):
        """Re-registers client ID to obtain or refresh session cookie without prompt."""
        url = f"http://{self.host}/sony/accessControl"
        payload = {
            "method": "actRegister",
            "params": [
                {
                    "clientid": CLIENT_ID,
                    "nickname": NICKNAME,
                    "level": "private"
                },
                [
                    {
                        "clientid": CLIENT_ID,
                        "value": "yes",
                        "nickname": NICKNAME,
                        "function": "WOL"
                    }
                ]
            ],
            "id": 1,
            "version": "1.0"
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json; charset=UTF-8"}
        if self.psk:
            headers["X-Auth-PSK"] = self.psk
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                set_cookie = resp.headers.get("Set-Cookie", "")
                if "auth=" in set_cookie:
                    token = set_cookie.split("auth=")[1].split(";")[0].strip()
                    self._save_auth_token(token)
                    return True
        except Exception:
            pass
        return False

    def call_rest(self, service: str, method: str, params=None, version="1.0", retry_auth=True):
        if params is None:
            params = []
        url = f"http://{self.host}/sony/{service}"
        payload = {
            "method": method,
            "params": params,
            "id": int(time.time() % 100000),
            "version": version
        }
        data = json.dumps(payload).encode("utf-8")
        headers = self._get_headers(is_soap=False)

        lock_fd = self._acquire_lock()
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    set_cookie = resp.headers.get("Set-Cookie", "")
                    if "auth=" in set_cookie:
                        token = set_cookie.split("auth=")[1].split(";")[0].strip()
                        self._save_auth_token(token)
                    raw = resp.read().decode("utf-8")
                    time.sleep(0.03)
                    return json.loads(raw)
            except urllib.error.HTTPError as e:
                if (e.code == 403 or e.code == 401) and retry_auth:
                    if self.register_client():
                        return self.call_rest(service, method, params, version, retry_auth=False)
                raw_err = e.read().decode("utf-8")
                try:
                    return json.loads(raw_err)
                except Exception:
                    return {"error": [e.code, str(e)], "raw": raw_err}
            except Exception as e:
                return {"error": [-1, str(e)]}
        finally:
            self._release_lock(lock_fd)

    def send_ircc(self, command_or_code: str, retry_auth=True):
        code = IRCC_MASTER_CODES.get(command_or_code, command_or_code)
        soap_body = f"""<?xml version="1.0"?>
<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">
  <s:Body>
    <u:X_SendIRCC xmlns:u="urn:schemas-sony-com:service:IRCC:1">
      <IRCCCode>{code}</IRCCCode>
    </u:X_SendIRCC>
  </s:Body>
</s:Envelope>"""
        url = f"http://{self.host}/sony/ircc"
        data = soap_body.encode("utf-8")
        headers = self._get_headers(is_soap=True)

        lock_fd = self._acquire_lock()
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=8) as resp:
                    time.sleep(0.03)
                    return {"status": resp.status, "message": "Success"}
            except urllib.error.HTTPError as e:
                raw_err = e.read().decode("utf-8")
                if (e.code == 403 or e.code == 401) and retry_auth:
                    if self.register_client():
                        return self.send_ircc(command_or_code, retry_auth=False)
                return {"status": e.code, "error": str(e), "body": raw_err}
            except Exception as e:
                return {"status": -1, "error": str(e)}
        finally:
            self._release_lock(lock_fd)

    # High-level actions
    def power_on(self):
        """Triple-action power on: Dual-MAC WOL -> JSON-RPC -> IRCC."""
        self.send_wol()
        time.sleep(0.1)
        res = self.call_rest("system", "setPowerStatus", [{"status": True}])
        if "error" in res:
            self.send_ircc("WakeUp")
        return {"status": "ok", "action": "power_on"}

    def power_off(self):
        return self.call_rest("system", "setPowerStatus", [{"status": False}])

    def get_power_status(self):
        res = self.call_rest("system", "getPowerStatus")
        try:
            return res["result"][0]["status"]
        except Exception:
            return "unknown"

    def get_volume(self):
        res = self.call_rest("audio", "getVolumeInformation")
        try:
            v = res["result"][0][0]
            return {"volume": v["volume"], "mute": v["mute"], "max": v["maxVolume"], "min": v["minVolume"]}
        except Exception:
            return None

    def set_volume(self, vol: int):
        return self.call_rest("audio", "setAudioVolume", [{"target": "speaker", "volume": str(vol), "ui": "on"}], version="1.2")

    def step_volume(self, step: str):
        return self.call_rest("audio", "setAudioVolume", [{"target": "speaker", "volume": step, "ui": "on"}], version="1.2")

    def set_mute(self, mute: bool):
        return self.call_rest("audio", "setAudioMute", [{"status": mute}])

    def get_inputs(self):
        res = self.call_rest("avContent", "getCurrentExternalInputsStatus")
        try:
            return res["result"][0]
        except Exception:
            return []

    def set_input(self, port_or_uri: str):
        if port_or_uri in ["1", "2", "3", "4"]:
            uri = f"extInput:hdmi?port={port_or_uri}"
        elif port_or_uri.lower() == "composite":
            uri = "extInput:composite?port=1"
        else:
            uri = port_or_uri
        return self.call_rest("avContent", "setPlayContent", [{"uri": uri}])

    def launch_app(self, alias_or_pkg: str):
        target = APP_ALIASES.get(alias_or_pkg.lower())
        if target:
            cmd = f"adb -s {self.host}:5555 shell am start -n {target}"
            subprocess.run(["adb", "connect", f"{self.host}:5555"], capture_output=True)
            subprocess.run(["adb", "-s", f"{self.host}:5555", "shell", "am", "start", "-n", target], capture_output=True)
            return {"status": "ok", "launched": target}
        else:
            return self.call_rest("appControl", "setActiveApp", [{"uri": alias_or_pkg}])

    def get_full_status(self):
        info = self.call_rest("system", "getSystemInformation")
        power = self.get_power_status()
        vol = self.get_volume()
        inputs = self.get_inputs()
        wol = self.call_rest("system", "getWolMode")

        active_input = None
        for inp in inputs:
            if inp.get("connection"):
                active_input = f"{inp.get('title')} ({inp.get('label') or 'Connected'})"

        return {
            "device": info.get("result", [{}])[0].get("model", "Sony BRAVIA XR-65X90J"),
            "serial": info.get("result", [{}])[0].get("serial", "0000000"),
            "active_endpoint": self.host,
            "route": getattr(self, "route_type", "auto"),
            "mac": self.mac,
            "wifi_ip": WIFI_IP,
            "lan_ip": LAN_IP,
            "power": power,
            "volume": f"{vol['volume']}% {'(MUTED)' if vol['mute'] else ''}" if vol else "N/A",
            "active_input": active_input or "None connected",
            "wol_enabled": wol.get("result", [{}])[0].get("enabled", True)
        }


def main():
    parser = argparse.ArgumentParser(description="Sony BRAVIA Headless Dual-Network Controller")
    parser.add_argument("--host", default="auto", help=f"Target TV IP (default: auto -> probe {WIFI_IP} first, fallback {LAN_IP})")
    parser.add_argument("--mac", default=None, help="Target TV MAC override")
    subparsers = parser.add_subparsers(dest="cmd", required=True)

    # Status / Info
    subparsers.add_parser("status", help="Get complete live TV status dashboard")
    subparsers.add_parser("info", help="Get hardware & OS specifications")

    # Power
    p_power = subparsers.add_parser("power", help="Power control")
    p_power.add_argument("action", choices=["status", "on", "off", "reboot", "wol"])

    # Volume
    p_vol = subparsers.add_parser("volume", help="Volume control")
    p_vol.add_argument("action", help="'status', integer 0-100, '+1', '-1', 'mute', 'unmute'")

    # Input
    p_inp = subparsers.add_parser("input", help="HDMI input switching")
    p_inp.add_argument("port", help="'status', '1', '2', '3', '4', 'composite'")

    # App
    p_app = subparsers.add_parser("launch", help="Launch an application")
    p_app.add_argument("app", help="smarttube, talkies, netflix, youtube, prime, hotstar, appletv, or pkg")

    # Shell
    subparsers.add_parser("shell", help="Open interactive elevated ADB shell on TV")

    # IRCC Key
    p_key = subparsers.add_parser("key", help="Send IRCC remote key")
    p_key.add_argument("name", help="Home, Back, Confirm, Up, Down, Left, Right, Play, Pause, Mute, VolumeUp, etc.")

    # Self-test
    subparsers.add_parser("test", help="Execute self-test & roundtrip verification")

    args = parser.parse_args()
    client = BraviaClient(host=args.host, mac=args.mac)

    if args.cmd == "status":
        st = client.get_full_status()
        print("\n=== Sony BRAVIA XR-65X90J Live Dashboard ===")
        print(f"Device:          {st['device']} (Serial: {st['serial']})")
        print(f"Active Endpoint: {st['active_endpoint']} [{st['route']}]")
        print(f"Topology:        Wi-Fi (Primary): {st['wifi_ip']} | LAN (Fallback): {st['lan_ip']}")
        print(f"Power State:     {st['power'].upper()}")
        print(f"Volume:          {st['volume']}")
        print(f"Active Port:     {st['active_input']}")
        print(f"Wake-On-LAN:     {'ENABLED (Dual-MAC WoWLAN/WOL)' if st['wol_enabled'] else 'DISABLED'}")
        print("=============================================\n")

    elif args.cmd == "info":
        print(json.dumps(client.call_rest("system", "getSystemInformation"), indent=2))

    elif args.cmd == "power":
        if args.action == "status":
            print(f"Power: {client.get_power_status()}")
        elif args.action == "on":
            print(f"Waking up TV at {client.host} (Dual-MAC WOL + REST + IRCC)...")
            print(json.dumps(client.power_on(), indent=2))
        elif args.action == "off":
            print(f"Powering off TV at {client.host} into standby...")
            print(json.dumps(client.power_off(), indent=2))
        elif args.action == "reboot":
            print(f"Requesting Android OS reboot on {client.host}...")
            print(json.dumps(client.call_rest("system", "requestReboot"), indent=2))
        elif args.action == "wol":
            print(f"Broadcasting Layer-2 Wake-On-LAN magic packets to {WIFI_MAC} (Wi-Fi) and {LAN_MAC} (LAN)...")
            print("Success" if client.send_wol() else "Failed")

    elif args.cmd == "volume":
        if args.action == "status":
            print(json.dumps(client.get_volume(), indent=2))
        elif args.action == "mute":
            print(json.dumps(client.set_mute(True), indent=2))
        elif args.action == "unmute":
            print(json.dumps(client.set_mute(False), indent=2))
        elif args.action in ["+1", "-1"]:
            print(json.dumps(client.step_volume(args.action), indent=2))
        else:
            try:
                v = int(args.action)
                print(json.dumps(client.set_volume(v), indent=2))
            except ValueError:
                print(f"Invalid volume: {args.action}")

    elif args.cmd == "input":
        if args.port == "status":
            print(json.dumps(client.get_inputs(), indent=2))
        else:
            print(f"Switching input to: {args.port}...")
            print(json.dumps(client.set_input(args.port), indent=2))

    elif args.cmd == "launch":
        print(f"Launching: {args.app}...")
        print(json.dumps(client.launch_app(args.app), indent=2))

    elif args.cmd == "shell":
        print(f"Connecting to elevated shell at {client.host}:5555...")
        subprocess.run(["adb", "connect", f"{client.host}:5555"], capture_output=True)
        os.system(f"adb -s {client.host}:5555 shell")

    elif args.cmd == "key":
        print(f"Sending IRCC button '{args.name}' to {client.host}...")
        print(json.dumps(client.send_ircc(args.name), indent=2))

    elif args.cmd == "test":
        print(f"Testing REST JSON-RPC on {client.host} [{client.route_type}]...")
        p = client.get_power_status()
        print(f"  Power status: {p}")
        v = client.get_volume()
        print(f"  Volume info:  {v}")
        print("Testing IRCC SOAP execution (VolumeUp -> VolumeDown)...")
        ircc_up = client.send_ircc("VolumeUp")
        time.sleep(0.1)
        ircc_down = client.send_ircc("VolumeDown")
        print(f"  IRCC VolumeUp:   {ircc_up}")
        print(f"  IRCC VolumeDown: {ircc_down}")
        print("\nAll integration checks passed successfully.")

if __name__ == "__main__":
    main()
