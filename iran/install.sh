#!/usr/bin/env bash
# ============================================================
#  Seamless Iran Agent — Offline Installer  v2.0
#
#  Requirements on the Iran server:
#    - Python 3.8+  (almost always pre-installed on Ubuntu/Debian)
#    - systemd
#    - No internet access needed — everything runs from this bundle.
#
#  Usage:
#    sudo bash install.sh
#
#  Supported outbound modes:
#    1) direct       — Agent connects directly to the foreign server
#    2) http_proxy   — Agent uses an existing HTTP/HTTPS proxy
#    3) xray_vless   — Agent tunnels through a local Xray VLESS proxy
#                      (requires iran/xray/xray binary inside the bundle)
# ============================================================
set -euo pipefail

INSTALL_DIR="/opt/seamless-iran-agent"
SERVICE_NAME="seamless-iran-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Xray local proxy settings
XRAY_LOCAL_HOST="127.0.0.1"
XRAY_LOCAL_PORT="10809"
XRAY_CONFIG_DIR="/etc/xray"

RED="\033[0;31m"; GREEN="\033[0;32m"; YELLOW="\033[0;33m"
CYAN="\033[0;36m"; NC="\033[0m"
info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*" >&2; }
die()     { error "$*"; exit 1; }

ask() {
    local var="$1" prompt="$2" default="${3:-}"
    local display_default=""
    [[ -n "$default" ]] && display_default=" [${default}]"
    printf "%b%s%s: %b" "${CYAN}" "${prompt}" "${display_default}" "${NC}"
    read -r answer
    answer="${answer:-$default}"
    eval "${var}=\"\${answer}\""
}

ask_secret() {
    local var="$1" prompt="$2"
    printf "%b%s: %b" "${CYAN}" "${prompt}" "${NC}"
    read -rs answer; echo
    eval "${var}=\"\${answer}\""
}

# ── Banner ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║   Seamless Iran Agent — Offline Installer v2.0      ║${NC}"
echo -e "${CYAN}║   3x-ui Panel Connector · No internet required      ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""

# ── Root check ─────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && die "This installer must be run as root (or with sudo)."

# ── Step 1: Check Python 3 ─────────────────────────────────────────────────────
info "Checking for Python 3 (must be pre-installed)..."
PYTHON=""
for candidate in python3 python3.11 python3.10 python3.9 python3.8; do
    if command -v "$candidate" &>/dev/null; then
        PYTHON=$(command -v "$candidate")
        break
    fi
done

[[ -z "$PYTHON" ]] && die \
    "Python 3 is not installed and cannot be installed offline.\n" \
    "Please install Python 3.8+ on this server before running the installer."

PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")

[[ "$PY_MAJOR" -lt 3 || ( "$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 8 ) ]] && \
    die "Python 3.8+ is required. Found: $PY_VER"

success "Python $PY_VER found at $PYTHON"
info "Note: No pip install will be performed — the agent uses only stdlib."

# ── Step 2: Choose outbound mode ───────────────────────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Outbound Mode${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "  1) direct       — Connect directly to the foreign server"
echo "  2) http_proxy   — Use an existing HTTP/HTTPS proxy"
echo "  3) xray_vless   — Use bundled Xray with a VLESS outbound"
echo ""
ask OUTBOUND_MODE "Choose mode (1/2/3)" "1"

case "$OUTBOUND_MODE" in
    1|direct)       OUTBOUND_MODE="direct" ;;
    2|http_proxy)   OUTBOUND_MODE="http_proxy" ;;
    3|xray_vless)   OUTBOUND_MODE="xray_vless" ;;
    *) die "Invalid choice: $OUTBOUND_MODE" ;;
esac

PROXY_URL=""

# ── Mode: http_proxy ───────────────────────────────────────────────────────────
if [[ "$OUTBOUND_MODE" == "http_proxy" ]]; then
    echo ""
    ask PROXY_URL "HTTP proxy URL (e.g. http://1.2.3.4:3128)" ""
    [[ -z "$PROXY_URL" ]] && die "Proxy URL cannot be empty for http_proxy mode."
    success "Mode: http_proxy via $PROXY_URL"

# ── Mode: xray_vless ──────────────────────────────────────────────────────────
elif [[ "$OUTBOUND_MODE" == "xray_vless" ]]; then
    echo ""
    info "Checking for bundled Xray binary..."
    XRAY_LOCAL_BINARY="${SCRIPT_DIR}/xray/xray"
    if [[ ! -f "$XRAY_LOCAL_BINARY" ]]; then
        echo ""
        echo -e "${RED}════════════════════════════════════════════════════════${NC}"
        echo -e "${RED}  ERROR: Local Xray binary not found.                  ${NC}"
        echo -e "${RED}                                                       ${NC}"
        echo -e "${RED}  Expected file:  iran/xray/xray                      ${NC}"
        echo -e "${RED}                                                       ${NC}"
        echo -e "${RED}  Download ONCE on a machine with internet access:    ${NC}"
        echo -e "${RED}  https://github.com/XTLS/Xray-core/releases          ${NC}"
        echo -e "${RED}  File: Xray-linux-64.zip  →  extract binary 'xray'  ${NC}"
        echo -e "${RED}  Place at:  iran/xray/xray  then rebuild iran.zip    ${NC}"
        echo -e "${RED}════════════════════════════════════════════════════════${NC}"
        echo ""
        exit 1
    fi
    success "Bundled Xray binary found: $XRAY_LOCAL_BINARY"

    echo ""
    echo "Paste your VLESS URI below (single line, starting with vless://):"
    ask VLESS_URI "VLESS URI" ""
    [[ -z "$VLESS_URI" ]] && die "VLESS URI cannot be empty."
    [[ "$VLESS_URI" != vless://* ]] && die "URI must start with 'vless://'"

    PROXY_URL="http://${XRAY_LOCAL_HOST}:${XRAY_LOCAL_PORT}"
    success "Mode: xray_vless → local proxy at $PROXY_URL"
fi

# ── Step 3: Gather agent configuration ────────────────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Agent Configuration${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "You can find the Bot API URL and Registration Token inside the"
echo "Telegram bot admin panel:"
echo "  ⚙️ Admin Panel → 🇮🇷 Iran Panels → 🔑 Registration Tokens → Create"
echo ""
echo "Note: No internet download is required on this server."
echo "      The agent uses only Python standard library modules."
echo ""

ask    API_BASE_URL   "Bot API Base URL (e.g. http://1.2.3.4:8080)" ""
ask    REG_TOKEN      "Registration Token" ""
ask    AGENT_NAME     "Agent display name" "Iran Agent 1"
echo ""
echo "── 3x-ui Panel ──"
ask    PANEL_NAME     "Panel display name"                    "My Iran Panel"
ask    PANEL_HOST     "Panel host / IP"                       "127.0.0.1"
ask    PANEL_PORT     "Panel port"                            "2053"
ask    PANEL_PATH     "Panel URL path prefix (blank = none)"  ""
ask    PANEL_USERNAME "Panel username"                        "admin"
ask_secret PANEL_PASSWORD "Panel password"
echo ""
echo "── Timing ──"
ask    HEARTBEAT_SEC  "Heartbeat interval (seconds)"          "60"
ask    TEST_INTERVAL  "Panel test interval (seconds)"         "300"
ask    REQ_TIMEOUT    "HTTP request timeout (seconds)"        "15"

# ── Validate required inputs ───────────────────────────────────────────────────
[[ -z "$API_BASE_URL" ]]   && die "Bot API Base URL cannot be empty."
[[ -z "$REG_TOKEN" ]]      && die "Registration Token cannot be empty."
[[ -z "$PANEL_HOST" ]]     && die "Panel Host cannot be empty."
[[ -z "$PANEL_USERNAME" ]] && die "Panel Username cannot be empty."
[[ -z "$PANEL_PASSWORD" ]] && die "Panel Password cannot be empty."

# ── Step 4: Install Xray (xray_vless mode only) ────────────────────────────────
if [[ "$OUTBOUND_MODE" == "xray_vless" ]]; then
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  Installing Xray${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

    # Parse VLESS URI and build Xray config (pure Python stdlib — no pip needed)
    info "Parsing VLESS URI and building Xray config..."
    XRAY_CFG_TMP="$(mktemp /tmp/xray_config_XXXXXX.json)"

    "$PYTHON" - <<PYEOF
import sys, json
sys.path.insert(0, "${SCRIPT_DIR}/xray")
try:
    from parse_vless import parse_vless, VlessParseError
    from build_xray_config import build_config
except ImportError as e:
    print(f"ERROR: Cannot import xray helpers: {e}", file=sys.stderr)
    sys.exit(1)

uri = """${VLESS_URI}"""
try:
    info = parse_vless(uri.strip())
except VlessParseError as e:
    print(f"ERROR: Invalid VLESS URI: {e}", file=sys.stderr)
    sys.exit(1)

cfg = build_config(info, local_port=10809)
with open("${XRAY_CFG_TMP}", "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2, ensure_ascii=False)
print("Xray config written to ${XRAY_CFG_TMP}")
PYEOF

    success "VLESS URI parsed and Xray config generated"

    # Install Xray using local installer (no internet)
    info "Installing Xray binary and service..."
    mkdir -p "$XRAY_CONFIG_DIR"
    cp "$XRAY_CFG_TMP" "${XRAY_CONFIG_DIR}/config.json"
    chmod 600 "${XRAY_CONFIG_DIR}/config.json"
    rm -f "$XRAY_CFG_TMP"

    bash "${SCRIPT_DIR}/xray/install_xray.sh"

    # Test that the local proxy is reachable
    info "Testing Xray proxy connectivity to Bot API..."
    sleep 3
    if command -v curl &>/dev/null; then
        if curl -s --max-time 10 --proxy "$PROXY_URL" "${API_BASE_URL}/health" \
                -o /dev/null -w "%{http_code}" 2>/dev/null | grep -qE '^[23]'; then
            success "Xray proxy connectivity to Bot API: OK"
        else
            warn "Xray proxy test did not get a 2xx/3xx response from Bot API."
            warn "The agent will still try to connect — check logs if it fails."
        fi
    else
        warn "curl not found — skipping Xray proxy connectivity test."
        warn "You can test manually: curl -x $PROXY_URL ${API_BASE_URL}/health"
    fi
fi

# ── Step 5: Copy files to install directory ────────────────────────────────────
echo ""
info "Installing to $INSTALL_DIR ..."
mkdir -p "$INSTALL_DIR"

# Copy all agent files, excluding git / cache / unnecessary artifacts
rsync -a --exclude='.git' --exclude='__pycache__' \
    --exclude='*.pyc' --exclude='.env' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/" 2>/dev/null \
    || cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"

success "Files copied to $INSTALL_DIR"

# ── Step 6: Write config.env ───────────────────────────────────────────────────
CONFIG_FILE="${INSTALL_DIR}/config.env"
info "Writing config.env..."

cat > "$CONFIG_FILE" <<EOF
# Seamless Iran Agent — generated by install.sh $(date -u '+%Y-%m-%d %H:%M UTC')

BOT_API_URL=${API_BASE_URL}
REGISTRATION_TOKEN=${REG_TOKEN}
AGENT_NAME=${AGENT_NAME}
PANEL_NAME=${PANEL_NAME}
PANEL_HOST=${PANEL_HOST}
PANEL_PORT=${PANEL_PORT}
PANEL_PATH=${PANEL_PATH}
PANEL_USERNAME=${PANEL_USERNAME}
PANEL_PASSWORD=${PANEL_PASSWORD}
HEARTBEAT_INTERVAL=${HEARTBEAT_SEC}
PANEL_TEST_INTERVAL=${TEST_INTERVAL}
REQUEST_TIMEOUT=${REQ_TIMEOUT}
PROXY_URL=${PROXY_URL}

# Filled in automatically after successful registration:
AGENT_UUID=
AGENT_SECRET=

LOG_LEVEL=INFO
LOG_FILE=${INSTALL_DIR}/agent.log
EOF

chmod 600 "$CONFIG_FILE"
success "config.env written (mode: ${OUTBOUND_MODE})"

# ── Step 7: Register with the Bot API ─────────────────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Registering Agent${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
info "Registering agent with Bot API (using stdlib urllib only)..."
cd "$INSTALL_DIR"
if "$PYTHON" "$INSTALL_DIR/register.py"; then
    success "Registration successful!"
else
    echo ""
    error "Registration FAILED."
    echo "  Common reasons:"
    echo "    - Bot API URL is wrong or the foreign server is unreachable"
    echo "    - Registration token has expired or was already used"
    echo "    - PROXY_URL is wrong (check xray logs: journalctl -u xray -f)"
    echo ""
    echo "  Fix the issue, then re-run:"
    echo "    cd $INSTALL_DIR && $PYTHON register.py"
    exit 1
fi

# ── Step 8: Test panel login ───────────────────────────────────────────────────
info "Testing 3x-ui panel login..."
if "$PYTHON" "$INSTALL_DIR/test_panel.py" --local; then
    success "Panel login test passed!"
else
    warn "Panel login test FAILED."
    warn "Check panel credentials in $CONFIG_FILE"
    warn "Re-test anytime: cd $INSTALL_DIR && $PYTHON test_panel.py --local"
fi

# ── Step 9: Install systemd service ───────────────────────────────────────────
if command -v systemctl &>/dev/null; then
    echo ""
    info "Installing systemd service: $SERVICE_NAME"

    cat > "$SERVICE_FILE" <<UNIT
[Unit]
Description=Seamless Iran Agent — 3x-ui Panel Connector
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${PYTHON} ${INSTALL_DIR}/agent.py
Restart=on-failure
RestartSec=15s
EnvironmentFile=${CONFIG_FILE}
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
UNIT

    chmod 644 "$SERVICE_FILE"
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
    sleep 2

    if systemctl is-active --quiet "$SERVICE_NAME"; then
        success "Service $SERVICE_NAME is running"
    else
        warn "Service did not start — check logs:"
        echo "     journalctl -u $SERVICE_NAME -n 40 --no-pager"
    fi
else
    warn "systemctl not found — skipping service installation."
    warn "Start the agent manually:"
    echo "    cd $INSTALL_DIR && $PYTHON agent.py"
fi

# ── Done ───────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Installation complete!                             ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo "  Install dir : $INSTALL_DIR"
echo "  Config      : $CONFIG_FILE"
echo "  Mode        : $OUTBOUND_MODE"
[[ -n "$PROXY_URL" ]] && echo "  Proxy       : $PROXY_URL"
echo ""
echo "  Useful commands:"
echo "    systemctl status $SERVICE_NAME"
echo "    journalctl -u $SERVICE_NAME -f"
[[ "$OUTBOUND_MODE" == "xray_vless" ]] && \
    echo "    systemctl status xray"
[[ "$OUTBOUND_MODE" == "xray_vless" ]] && \
    echo "    journalctl -u xray -f"
echo "    cd $INSTALL_DIR && $PYTHON healthcheck.py"
echo ""
