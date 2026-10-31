#!/usr/bin/env bash
# ==============================================================================
# Sony BRAVIA TV Suite — Unified Management Wrapper
# Target: Sony BRAVIA XR-65X90J (Dual-Network: Wi-Fi Primary / LAN Fallback)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTROLLER="${SCRIPT_DIR}/sony_bravia_controller.py"
CLEAN_SLATE="${SCRIPT_DIR}/sony_clean_slate_talkies.py"
RESTORE="${SCRIPT_DIR}/restore_stock_sony.py"
CONFIG_FILE="${SCRIPT_DIR}/../config/bravia_config.json"
ENV_FILE="${SCRIPT_DIR}/../.env"

# Source .env if present
if [ -f "${ENV_FILE}" ]; then
    # shellcheck disable=SC1090
    set -a && source "${ENV_FILE}" && set +a
fi

# Load IPs dynamically from untracked config/bravia_config.json if available
if [ -f "${CONFIG_FILE}" ] && command -v python3 >/dev/null 2>&1; then
    WIFI_IP="${SONY_TV_WIFI_IP:-$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('network',{}).get('wifi',{}).get('ip','192.168.1.100'))" 2>/dev/null || echo "192.168.1.100")}"
    LAN_IP="${SONY_TV_LAN_IP:-$(python3 -c "import json; print(json.load(open('${CONFIG_FILE}')).get('network',{}).get('lan',{}).get('ip','10.42.0.100'))" 2>/dev/null || echo "10.42.0.100")}"
else
    WIFI_IP="${SONY_TV_WIFI_IP:-192.168.1.100}"
    LAN_IP="${SONY_TV_LAN_IP:-10.42.0.100}"
fi

resolve_tv_ip() {
    if [ -n "${SONY_TV_IP:-}" ]; then
        echo "${SONY_TV_IP}"
        return
    fi
    # Probe Primary Wi-Fi (5555 or 80)
    if timeout 0.4 bash -c "</dev/tcp/${WIFI_IP}/5555" 2>/dev/null || timeout 0.4 bash -c "</dev/tcp/${WIFI_IP}/80" 2>/dev/null; then
        echo "${WIFI_IP}"
        return
    fi
    # Probe Fallback LAN (5555 or 80)
    if timeout 0.4 bash -c "</dev/tcp/${LAN_IP}/5555" 2>/dev/null || timeout 0.4 bash -c "</dev/tcp/${LAN_IP}/80" 2>/dev/null; then
        echo "${LAN_IP}"
        return
    fi
    # Standby default: Wi-Fi primary
    echo "${WIFI_IP}"
}

TV_IP="$(resolve_tv_ip)"

usage() {
    cat <<EOF
Sony BRAVIA Suite Management CLI
Target: Sony BRAVIA XR-65X90J [Detected: ${TV_IP}]

Usage: $(basename "$0") <command> [arguments]

Commands:
  status             Show live TV status dashboard (power, volume, input, network)
  shell              Open interactive elevated ADB shell on the TV
  power [action]     Power control: on, off, reboot, status, wol (default: status)
  clean              Apply safe debloat/clean-slate & pin Talkies launcher (--apply)
  check              Run read-only pre-flight dependency & risk audit (--check)
  restore            Restore 100% stock factory system packages & settings
  help, -h, --help   Display this help message

Network Modes:
  Primary:  Wi-Fi — Deterministic static DHCP reservation on router
  Fallback: LAN   — Temporary direct Ethernet connection

Examples:
  ./manage.sh status
  ./manage.sh power on
  ./manage.sh power off
  ./manage.sh check
  ./manage.sh clean
  ./manage.sh restore
  ./manage.sh shell
EOF
}

# Ensure ADB connection if device is offline/disconnected
ensure_adb() {
    if ! adb devices | grep -q "${TV_IP}:5555.*device"; then
        adb connect "${TV_IP}:5555" >/dev/null 2>&1 || true
    fi
}

COMMAND="${1:-}"

case "${COMMAND}" in
    status)
        exec python3 "${CONTROLLER}" status
        ;;
    shell)
        ensure_adb
        exec python3 "${CONTROLLER}" shell
        ;;
    power)
        ACTION="${2:-status}"
        exec python3 "${CONTROLLER}" power "${ACTION}"
        ;;
    clean)
        ensure_adb
        exec python3 "${CLEAN_SLATE}" --target "${TV_IP}:5555" --apply "${@:2}"
        ;;
    check)
        ensure_adb
        exec python3 "${CLEAN_SLATE}" --target "${TV_IP}:5555" --check "${@:2}"
        ;;
    restore)
        ensure_adb
        exec python3 "${RESTORE}" --target "${TV_IP}:5555" "${@:2}"
        ;;
    help|-h|--help)
        usage
        exit 0
        ;;
    "")
        usage
        exit 1
        ;;
    *)
        echo "Unknown command: ${COMMAND}" >&2
        echo "" >&2
        usage >&2
        exit 1
        ;;
esac
