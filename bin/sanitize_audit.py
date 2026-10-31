#!/usr/bin/env python3
"""
Sony BRAVIA Suite — Automated Sanitization & Secret Audit Scanner
Ensures no sensitive credentials, active session tokens, real device serials,
or private network secrets are committed to version control.

Design:
  - Dynamically extracts private identifiers from untracked config/bravia_config.json
    and enforces that none of them appear in version-controlled files.
  - Enforces generic structural checks (masks on MACs, private IPs, tokens, and PSKs).
  - Contains ZERO hardcoded private secrets or plaintext user telemetry.

Exit codes:
  0: Clean repository (no leaks detected)
  1: Leaks or untracked secret files detected
"""

import sys
import os
import re
import json
import subprocess
from pathlib import Path

# Base repository root directory
SUITE_DIR = Path(__file__).resolve().parent.parent

# Files that MUST NEVER be tracked or committed
FORBIDDEN_TRACKED_FILENAMES = {
    "cookies.txt",
    "sony_bravia_cookies.txt",
    ".env",
    "local_config.json",
    "bravia_config.json",
}

# Generic structural patterns for sensitive data (applies anywhere)
GENERIC_SECRET_PATTERNS = [
    # 1. Unmasked 40-character hex WebAuth token (e.g. SHA1 hash)
    (
        re.compile(r'\b(?<!<AUTH_TOKEN_HASH>)(?<![0-9a-fA-F])[A-Fa-f0-9]{40}\b'),
        "Unmasked 40-character hex session token detected"
    ),
    # 2. Unmasked hardware MAC address (must be masked with XX:XX:XX or 00:00:00)
    (
        re.compile(r'\b(?!38:b8:00:00:00:00|f8:4e:17:00:00:00)(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b', re.IGNORECASE),
        "Unmasked hardware MAC address detected (must use XX:XX:XX or masked placeholder)"
    ),
    # 3. Unmasked private IP addresses (must use .100 or .x documentation convention)
    (
        re.compile(r'\b192\.168\.\d+\.(?!(?:100|255)\b)\d+\b'),
        "Unmasked private 192.168.x.x IP address detected (must use 192.168.1.100 or 192.168.1.x)"
    ),
    (
        re.compile(r'\b10\.42\.\d+\.(?!(?:100|255)\b)\d+\b'),
        "Unmasked private 10.42.x.x IP address detected (must use 10.42.0.100 or 10.42.0.x)"
    ),
    # 4. Live PSK assignment in config or environment
    (
        re.compile(r'(?:SONY_TV_PSK\s*=\s*["\']?(?!(?:YOUR_PSK_HERE|\$\{?\w+\}?|default|test|placeholder))([a-zA-Z0-9_\-!@#$%^&*]{2,})["\']?|["\']psk["\']\s*:\s*["\'](?!YOUR_PSK_HERE)[^"\']+["\'])', re.IGNORECASE),
        "Live Pre-Shared Key (PSK) detected in configuration"
    ),
    # 5. Private keys
    (
        re.compile(r'-----BEGIN\s+(?:RSA|OPENSSH|DSA|EC|PRIVATE)\s+KEY-----'),
        "Private cryptographic key block detected"
    ),
    # 6. Generic router or admin password assignment
    (
        re.compile(r'(?:router_password|admin_password|wifi_password)\s*[:=]\s*["\'][^"\']+["\']', re.IGNORECASE),
        "Router or Wi-Fi administrative password assignment detected"
    ),
]

# Dynamically extract local device values if untracked local config exists
def load_dynamic_banned_values():
    banned = set()
    local_cfg_path = SUITE_DIR / "config" / "bravia_config.json"
    if local_cfg_path.exists():
        try:
            with open(local_cfg_path, "r") as f:
                cfg = json.load(f)
                # Serial
                ser = str(cfg.get("device", {}).get("serial", "")).strip()
                if ser and ser != "0000000":
                    banned.add(ser)
                # Wi-Fi
                wifi = cfg.get("network", {}).get("wifi", {})
                w_ip = str(wifi.get("ip", "")).strip()
                if w_ip and w_ip != "192.168.1.100":
                    banned.add(w_ip)
                w_mac = str(wifi.get("mac", "")).strip()
                if w_mac and "XX" not in w_mac and "00:00:00" not in w_mac:
                    banned.add(w_mac.lower())
                    banned.add(w_mac.upper())
                w_ssid = str(wifi.get("ssid", "")).strip()
                if w_ssid and w_ssid != "YOUR_WIFI_SSID":
                    banned.add(w_ssid)
                # LAN
                lan = cfg.get("network", {}).get("lan", {})
                l_ip = str(lan.get("ip", "")).strip()
                if l_ip and l_ip != "10.42.0.100":
                    banned.add(l_ip)
                l_mac = str(lan.get("mac", "")).strip()
                if l_mac and "XX" not in l_mac and "00:00:00" not in l_mac:
                    banned.add(l_mac.lower())
                    banned.add(l_mac.upper())
                # PSK
                psk = str(cfg.get("auth", {}).get("psk", "")).strip()
                if psk and psk not in ("YOUR_PSK_HERE", "1234", "0000", "default"):
                    banned.add(psk)
        except Exception:
            pass
            
    # Also ban known infrastructure IPs if configured in environment
    pihole_ip = os.environ.get("PIHOLE_IP")
    if pihole_ip and pihole_ip.strip():
        banned.add(pihole_ip.strip())
    gateway_ip = os.environ.get("GATEWAY_IP")
    if gateway_ip and gateway_ip.strip():
        banned.add(gateway_ip.strip())

    return banned


DYNAMIC_BANNED = load_dynamic_banned_values()

# Files exempt from specific self-referential pattern scans
EXEMPT_FILES = {
    "bin/sanitize_audit.py",
}


def get_target_files(scan_all_disk: bool = False):
    """Retrieve list of files to inspect (tracked in Git, or all non-ignored on disk)."""
    files = []
    
    is_git = False
    try:
        res = subprocess.run(
            ["git", "-C", str(SUITE_DIR), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True
        )
        is_git = (res.returncode == 0 and res.stdout.strip() == "true")
    except Exception:
        is_git = False

    if is_git and not scan_all_disk:
        # Get tracked files
        res = subprocess.run(
            ["git", "-C", str(SUITE_DIR), "ls-files"],
            capture_output=True,
            text=True
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if line.strip():
                    files.append(SUITE_DIR / line.strip())
        
        # Also check staged files (index)
        res_staged = subprocess.run(
            ["git", "-C", str(SUITE_DIR), "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True
        )
        if res_staged.returncode == 0:
            for line in res_staged.stdout.splitlines():
                if line.strip():
                    p = SUITE_DIR / line.strip()
                    if p not in files:
                        files.append(p)
    else:
        for root, dirs, filenames in os.walk(SUITE_DIR):
            dirs[:] = [d for d in dirs if d not in {".git", "__pycache__", ".pytest_cache"}]
            for fname in filenames:
                p = Path(root) / fname
                if p.name in FORBIDDEN_TRACKED_FILENAMES or p.name.endswith(".pyc") or p.name.endswith(".lock"):
                    continue
                files.append(p)

    return sorted(list(set(files)))


def scan_file(file_path: Path):
    """Scan a single file for secret violations. Returns list of error tuples."""
    violations = []
    rel_path = file_path.relative_to(SUITE_DIR)
    rel_path_str = str(rel_path)

    # 1. Check if the file itself is a forbidden secret file
    if file_path.name in FORBIDDEN_TRACKED_FILENAMES:
        violations.append((0, f"FORBIDDEN FILE: '{rel_path_str}' must not be tracked in version control."))
        return violations

    # Skip binary files or non-existent files
    if not file_path.exists() or file_path.is_symlink() or not file_path.is_file():
        return violations

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
    except Exception as e:
        violations.append((0, f"UNREADABLE FILE: Could not read {rel_path_str}: {e}"))
        return violations

    # 2. Check each line against dynamic banned values from local config
    for idx, line in enumerate(lines, 1):
        if rel_path_str in EXEMPT_FILES:
            continue

        for val in DYNAMIC_BANNED:
            if not val or len(val) < 3:
                continue
            # Use boundary assertion to prevent false substring matches (e.g. .1 matching .100)
            pattern = re.compile(r'(?<![0-9a-zA-Z._])' + re.escape(val) + r'(?![0-9a-zA-Z._])', re.IGNORECASE)
            if pattern.search(line):
                masked = val[:2] + ("*" * (len(val) - 4)) + val[-2:] if len(val) > 4 else "***"
                violations.append((idx, f"Leaked local device private identifier -> Found match: '{masked}'"))

        # 3. Check generic patterns
        for pattern, desc in GENERIC_SECRET_PATTERNS:
            match = pattern.search(line)
            if match:
                matched_str = match.group(0)
                masked = matched_str[:2] + ("*" * (len(matched_str) - 4)) + matched_str[-2:] if len(matched_str) > 4 else "***"
                violations.append((idx, f"{desc} -> Found match: '{masked}'"))

    return violations


def main():
    print("=================================================================")
    print("      SONY BRAVIA SUITE — SANITIZATION & SECRET AUDIT SCANNER     ")
    print("=================================================================")

    target_files = get_target_files(scan_all_disk=False)
    if not target_files:
        print("[!] Warning: No tracked files found to inspect.")
        sys.exit(0)

    print(f"[*] Scanning {len(target_files)} target file(s)...")
    if DYNAMIC_BANNED:
        print(f"[*] Loaded {len(DYNAMIC_BANNED)} local private identifier(s) for active leak detection.")

    total_violations = 0
    files_with_violations = 0

    for file_path in target_files:
        violations = scan_file(file_path)
        if violations:
            files_with_violations += 1
            total_violations += len(violations)
            rel_path = file_path.relative_to(SUITE_DIR)
            print(f"\n[FAIL] Security violations detected in: {rel_path}")
            for line_no, desc in violations:
                if line_no > 0:
                    print(f"       Line {line_no:4d}: {desc}")
                else:
                    print(f"       {desc}")

    print("\n-----------------------------------------------------------------")
    if total_violations == 0:
        print(f"[PASS] Audit CLEAN. All {len(target_files)} files verified safe for version control.")
        print("=================================================================")
        sys.exit(0)
    else:
        print(f"[FAIL] Audit FAILED: {total_violations} security violation(s) detected across repository.")
        print("       Action required: Sanitize secrets or add untracked files to .gitignore.")
        print("=================================================================")
        sys.exit(1)


if __name__ == "__main__":
    main()
