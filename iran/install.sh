#!/usr/bin/env bash
# ============================================================
#  Seamless Iran Agent — Interactive Installer
#  Tested on: Ubuntu 20.04 / 22.04, Debian 11/12
# ============================================================
set -euo pipefail

# ── Constants ────────────────────────────────────────────────
INSTALL_DIR="/opt/seamless-iran-agent"
SERVICE_NAME="seamless-iran-agent"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED="\033[0;31m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
NC="\033[0m"

info()    { echo -e "${CYAN}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; }
die()     { error "$*"; exit 1; }

ask() {
    # ask <VAR_NAME> <prompt> [default]
    local var="$1" prompt="$2" default="${3:-}"
    local display_default=""
    [ -n "$default" ] && display_default=" [${default}]"
    printf "%b%s%s: %b" "${CYAN}" "${prompt}" "${display_default}" "${NC}"
    read -r answer
    answer="${answer:-$default}"
    eval "${var}=\"\${answer}\""
}

ask_secret() {
    local var="$1" prompt="$2"
    printf "%b%s: %b" "${CYAN}" "${prompt}" "${NC}"
    read -rs answer
    echo
    eval "${var}=\"\${answer}\""
}

# ── Banner ────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     Seamless Iran Agent — Installer v1.0         ║${NC}"
echo -e "${CYAN}║     3x-ui Panel Connector for Seamless VPN       ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ── Root check ────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    die "This installer must be run as root (or with sudo)."
fi

# ── Step 1: Check prerequisites ───────────────────────────────
info "Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    warn "python3 not found — attempting to install..."
    apt-get update -qq && apt-get install -y python3 python3-pip python3-venv \
        || die "Failed to install Python 3. Install it manually and re-run."
fi

PYTHON=$(command -v python3)
PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
info "Python version: $PY_VER"

if ! python3 -c "import venv" 2>/dev/null; then
    warn "python3-venv not found — installing..."
    apt-get install -y python3-venv || die "Failed to install python3-venv."
fi

success "Prerequisites OK"

# ── Step 2: Gather configuration ─────────────────────────────
echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Configuration${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo "Please enter the required information."
echo "You can find the API URL and Registration Token in your bot's"
echo "admin panel under: Iran Panels (secondary panels) -> Create Registration Token"
echo ""

ask    API_BASE_URL     "Bot API Base URL (e.g. http://1.2.3.4:8080)"
ask    REG_TOKEN        "Registration Token"
ask    AGENT_NAME       "Agent Name (display label)"         "Iran Agent 1"
echo ""
echo "── 3x-ui Panel Info ──"
ask    PANEL_NAME       "Panel Display Name"                  "My Iran Panel"
ask    PANEL_HOST       "Panel Host / IP"                     "127.0.0.1"
ask    PANEL_PORT       "Panel Port"                          "2053"
ask    PANEL_PATH       "Panel URL Path (leave blank if none)" ""
ask    PANEL_USERNAME   "Panel Username"                       "admin"
ask_secret PANEL_PASSWORD "Panel Password"
echo ""
echo "── Timing ──"
ask    HEARTBEAT_SEC    "Heartbeat interval (seconds)"        "60"
ask    TEST_INTERVAL    "Panel test interval (seconds)"       "300"
ask    REQ_TIMEOUT      "HTTP request timeout (seconds)"      "15"
ask    PROXY_URL        "Proxy URL (leave blank to skip)"     ""

# ── Validate minimal inputs ───────────────────────────────────
[ -z "$API_BASE_URL" ]    && die "API Base URL cannot be empty."
[ -z "$REG_TOKEN" ]       && die "Registration Token cannot be empty."
[ -z "$PANEL_HOST" ]      && die "Panel Host cannot be empty."
[ -z "$PANEL_USERNAME" ]  && die "Panel Username cannot be empty."
[ -z "$PANEL_PASSWORD" ]  && die "Panel Password cannot be empty."

# ── Step 3: Create install directory ─────────────────────────
info "Creating installation directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
rsync -a --exclude='.git' --exclude='__pycache__' \
    "$SCRIPT_DIR/" "$INSTALL_DIR/" 2>/dev/null \
    || cp -r "$SCRIPT_DIR/." "$INSTALL_DIR/"
success "Files copied to $INSTALL_DIR"

# ── Step 4: Python virtual environment ───────────────────────
VENV_DIR="$INSTALL_DIR/venv"
info "Creating Python virtual environment..."
"$PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
success "Dependencies installed"

# ── Step 5: Write config.env ──────────────────────────────────
CONFIG_FILE="$INSTALL_DIR/config.env"
info "Writing configuration to $CONFIG_FILE ..."

cat > "$CONFIG_FILE" <<EOF
# Seamless Iran Agent config — generated by install.sh
# $(date)

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

# Filled in automatically after registration:
AGENT_UUID=
AGENT_SECRET=

LOG_LEVEL=INFO
LOG_FILE=${INSTALL_DIR}/agent.log
EOF

chmod 600 "$CONFIG_FILE"
success "config.env written"

# ── Step 6: Register with bot API ────────────────────────────
info "Running registration with bot API..."
cd "$INSTALL_DIR"
if "$VENV_DIR/bin/python" "$INSTALL_DIR/register.py"; then
    success "Registration successful!"
else
    die "Registration failed. Check your API URL and token, then re-run install.sh."
fi

# ── Step 7: Test panel login ──────────────────────────────────
info "Testing 3x-ui panel login..."
if "$VENV_DIR/bin/python" "$INSTALL_DIR/test_panel.py" --local; then
    success "Panel login test passed!"
else
    warn "Panel login test FAILED. Check your panel credentials."
    warn "You can test again later with: python test_panel.py --local"
fi

# ── Step 8: Install systemd service ──────────────────────────
if command -v systemctl &>/dev/null; then
    info "Installing systemd service..."
    cat > "$SERVICE_FILE" <<UNIT
[Unit]
Description=Seamless Iran Agent — 3x-ui Panel Connector
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=${VENV_DIR}/bin/python ${INSTALL_DIR}/agent.py
Restart=on-failure
RestartSec=15s
EnvironmentFile=${CONFIG_FILE}
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=${INSTALL_DIR}

[Install]
WantedBy=multi-user.target
UNIT

    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME"
    success "systemd service installed and started"

    sleep 2
    if systemctl is-active --quiet "$SERVICE_NAME"; then
        success "Service is RUNNING"
    else
        warn "Service may not be running. Check: journalctl -u $SERVICE_NAME -n 30"
    fi
else
    warn "systemd not found — service not installed automatically."
    warn "Start agent manually with:"
    warn "  cd $INSTALL_DIR && venv/bin/python agent.py"
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║          Installation Complete! ✓                ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "Installation directory : $INSTALL_DIR"
echo "Config file            : $CONFIG_FILE"
echo "Log file               : $INSTALL_DIR/agent.log"
echo ""
echo "Useful commands:"
echo "  systemctl status $SERVICE_NAME"
echo "  journalctl -u $SERVICE_NAME -f"
echo "  $INSTALL_DIR/venv/bin/python $INSTALL_DIR/healthcheck.py"
echo ""
echo "The panel status will appear in your bot admin panel under:"
echo "  Settings -> Iran Panels (secondary panels)"
echo ""
