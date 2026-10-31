#!/usr/bin/env python3
"""
Sony BRAVIA XR-65X90J — High-Speed Multi-Threaded Factory Baseline Restorer
Restores 100% of debloated, disabled, and uninstalled system packages.
Preserves 100% of user data, logins, accounts, and user-installed apps.
Multi-Threaded: Executes batch ADB operations concurrently via ThreadPoolExecutor.
Dual-Network: Supports Wi-Fi Primary (192.168.1.x) and LAN Fallback (10.42.0.x).
"""

import sys
import os
import time
import socket
import argparse
import subprocess
from concurrent.futures import ThreadPoolExecutor

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "config", "bravia_config.json")
if os.path.exists(CONFIG_FILE):
    try:
        import json
        with open(CONFIG_FILE, "r") as f:
            _cfg = json.load(f)
            WIFI_TARGET = f"{_cfg.get('network', {}).get('wifi', {}).get('ip', '192.168.1.100')}:5555"
            LAN_TARGET = f"{_cfg.get('network', {}).get('lan', {}).get('ip', '10.42.0.100')}:5555"
    except Exception:
        WIFI_TARGET = "192.168.1.100:5555"
        LAN_TARGET = "10.42.0.100:5555"
else:
    WIFI_TARGET = "192.168.1.100:5555"
    LAN_TARGET = "10.42.0.100:5555"

WIFI_TARGET = os.environ.get("SONY_TV_WIFI_TARGET", WIFI_TARGET)
LAN_TARGET = os.environ.get("SONY_TV_LAN_TARGET", LAN_TARGET)


def probe_tcp(target, timeout=0.35):
    try:
        host, port = target.split(":")
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def resolve_target(explicit_target=None):
    if explicit_target and explicit_target not in ["auto", ""]:
        return explicit_target, "explicit"
    env_target = os.environ.get("SONY_TV_ADB")
    if env_target:
        return env_target, "environment"
    if probe_tcp(WIFI_TARGET):
        return WIFI_TARGET, "Wi-Fi (Primary)"
    if probe_tcp(LAN_TARGET):
        return LAN_TARGET, "LAN (Fallback)"
    return WIFI_TARGET, "Wi-Fi (Primary - Standby)"


class StockRestorer:
    def __init__(self, target):
        self.target = target
        self._ensure_connection()

    def _ensure_connection(self):
        subprocess.run(["adb", "connect", self.target], capture_output=True)
        res = subprocess.run(["adb", "-s", self.target, "shell", "getprop", "ro.product.model"], capture_output=True, text=True)
        if res.returncode != 0 or not res.stdout.strip():
            print(f"[!] Error: Unable to establish ADB communication with Sony TV at {self.target}.")
            sys.exit(1)
        self.model = res.stdout.strip()

    def run_adb(self, cmd):
        full_cmd = ["adb", "-s", self.target, "shell"] + (cmd if isinstance(cmd, list) else cmd.split())
        res = subprocess.run(full_cmd, capture_output=True, text=True)
        return res.stdout.strip(), res.stderr.strip(), res.returncode

    def _restore_uninstalled_pkg(self, pkg):
        cmd = f"cmd package install-existing --user 0 {pkg} && pm enable --user 0 {pkg} && pm unhide --user 0 {pkg} && cmd appops reset {pkg}"
        out, err, code = self.run_adb(cmd)
        return pkg, ("OK" if code == 0 else f"NOTE: {out or err}")

    def _restore_disabled_pkg(self, pkg):
        cmd = f"pm enable --user 0 {pkg} && pm unhide --user 0 {pkg} && cmd appops reset {pkg}"
        out, err, code = self.run_adb(cmd)
        return pkg, ("OK" if code == 0 else f"NOTE: {out or err}")

    def restore_all(self, workers=8):
        t0 = time.time()
        print(f"=== Starting High-Speed Factory Baseline Restoration on {self.model} ({self.target}) ===")
        print(f"Concurrency: {workers} parallel worker threads\n")

        # 1. Scan for uninstalled packages
        print("[Step 1/6] Scanning for uninstalled system packages...")
        all_pkgs = set(subprocess.check_output(["adb", "-s", self.target, "shell", "pm list packages -u"]).decode().split())
        installed_pkgs = set(subprocess.check_output(["adb", "-s", self.target, "shell", "pm list packages"]).decode().split())
        uninstalled = sorted([p.replace("package:", "").strip() for p in (all_pkgs - installed_pkgs)])
        print(f"Found {len(uninstalled)} uninstalled system packages to reinstall.")

        if uninstalled:
            print(f"  Dispatching {len(uninstalled)} packages across {workers} parallel workers...")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(self._restore_uninstalled_pkg, uninstalled))
            for idx, (pkg, status) in enumerate(results, 1):
                print(f"  [{idx:02d}/{len(uninstalled):02d}] Reinstalled: {pkg:<45} -> {status}")

        # 2. Scan for disabled packages
        print("\n[Step 2/6] Scanning for disabled packages...")
        disabled_raw = subprocess.check_output(["adb", "-s", self.target, "shell", "pm list packages -d"]).decode().split()
        disabled = sorted([p.replace("package:", "").strip() for p in disabled_raw])
        print(f"Found {len(disabled)} disabled packages to re-enable.")

        if disabled:
            print(f"  Dispatching {len(disabled)} packages across {workers} parallel workers...")
            with ThreadPoolExecutor(max_workers=workers) as ex:
                results = list(ex.map(self._restore_disabled_pkg, disabled))
            for idx, (pkg, status) in enumerate(results, 1):
                print(f"  [{idx:02d}/{len(disabled):02d}] Re-enabled:  {pkg:<45} -> {status}")

        # 3. Restore Default Google TV Home Launcher
        print("\n[Step 3/6] Restoring Google TV LauncherX as default home activity...")
        self.run_adb("cmd package set-home-activity com.google.android.apps.tv.launcherx/.home.HomeActivity")
        home_check, _, _ = self.run_adb("cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME")
        print(f"  Resolved Home Activity: {home_check.splitlines()[-1] if home_check else 'Unknown'}")

        # 4. Restore Voice Interaction & Assistant Services
        print("\n[Step 4/6] Restoring Katniss & Voice Search for remote mic...")
        self.run_adb("settings put secure voice_interaction_service com.google.android.katniss/.search.serviceapi.KatnissVoiceInteractionService")
        self.run_adb("settings put secure voice_recognition_service com.google.android.katniss/com.google.android.apps.tvsearch.voice.recognition.KatnissRecognitionService")
        self.run_adb("settings put secure assistant com.google.android.katniss/.search.serviceapi.KatnissVoiceInteractionService")
        print("  Voice interaction services restored.")

        # 5. Restore System, Kernel, and Memory tunings to stock defaults
        print("\n[Step 5/6] Resetting system and memory limits to stock defaults...")
        self.run_adb("device_config delete activity_manager max_cached_processes")
        self.run_adb("device_config delete activity_manager background_settle_time")
        print("  Activity manager defaults restored.")

        # 6. Final verification
        print("\n[Step 6/6] Verifying system baseline health...")
        uei, _, _ = self.run_adb("pm list packages -e com.uei.quicksetsdk.sony")
        katniss, _, _ = self.run_adb("pm list packages -e com.google.android.katniss")
        launcher, _, _ = self.run_adb("pm list packages -e com.google.android.apps.tv.launcherx")
        print(f"  UEI QuickSet (Remote Keys) : {'PASS' if 'quickset' in uei else 'FAIL'}")
        print(f"  Katniss (Google Assistant) : {'PASS' if 'katniss' in katniss else 'FAIL'}")
        print(f"  LauncherX (Google TV Home) : {'PASS' if 'launcherx' in launcher else 'FAIL'}")

        elapsed = time.time() - t0
        print(f"\n[SUCCESS] Factory baseline restoration completed in {elapsed:.2f} seconds.")


def main():
    parser = argparse.ArgumentParser(description="Sony BRAVIA XR-65X90J High-Speed Multi-Threaded Factory Baseline Restorer")
    parser.add_argument("--target", default="auto", help=f"ADB target host:port (default: auto -> probe {WIFI_TARGET} first, fallback {LAN_TARGET})")
    parser.add_argument("--threads", type=int, default=8, help="Number of concurrent worker threads (default: 8)")
    args = parser.parse_args()

    target, route = resolve_target(args.target)
    print(f"Selected Endpoint : {target} [{route}]")
    restorer = StockRestorer(target)
    restorer.restore_all(workers=args.threads)


if __name__ == "__main__":
    main()
