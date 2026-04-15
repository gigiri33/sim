#!/usr/bin/env bash
# ============================================================
#  Xray — Local Binary Installer
#  Installs the bundled xray binary and sets up its systemd
#  service.  No internet access required.
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_BINARY="${SCRIPT_DIR}/xray"
XRAY_BIN="/usr/local/bin/xray"
XRAY_CONFIG_DIR="/etc/xray"
XRAY_CONFIG="${XRAY_CONFIG_DIR}/config.json"
SERVICE_SRC="${SCRIPT_DIR}/service/xray.service"
SERVICE_DEST="/etc/systemd/system/xray.service"

RED="\033[0;31m"; GREEN="\033[0;32m"; CYAN="\033[0;36m"; NC="\033[0m"
info()    { echo -e "${CYAN}[xray]${NC} $*"; }
success() { echo -e "${GREEN}[xray OK]${NC} $*"; }
die()     { echo -e "${RED}[xray ERR]${NC} $*" >&2; exit 1; }

# ── Root check ─────────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && die "install_xray.sh must be run as root."

# ── Check local binary exists ─────────────────────────────────────────────────
if [[ ! -f "$LOCAL_BINARY" ]]; then
    echo ""
    echo -e "${RED}════════════════════════════════════════════════════${NC}"
    echo -e "${RED}  ERROR: Local Xray binary not found.               ${NC}"
    echo -e "${RED}                                                    ${NC}"
    echo -e "${RED}  Expected: iran/xray/xray                         ${NC}"
    echo -e "${RED}                                                    ${NC}"
    echo -e "${RED}  Please download the Linux xray binary once from: ${NC}"
    echo -e "${RED}  https://github.com/XTLS/Xray-core/releases       ${NC}"
    echo -e "${RED}  (e.g. Xray-linux-64.zip, extract 'xray' binary)  ${NC}"
    echo -e "${RED}  and place it at iran/xray/xray before building   ${NC}"
    echo -e "${RED}  iran.zip.                                         ${NC}"
    echo -e "${RED}════════════════════════════════════════════════════${NC}"
    echo ""
    exit 1
fi

# ── Verify it is executable / is actually a binary ────────────────────────────
if ! file "$LOCAL_BINARY" 2>/dev/null | grep -qiE 'ELF|executable'; then
    die "File at $LOCAL_BINARY does not look like a Linux ELF binary. " \
        "Make sure you downloaded the correct architecture (linux-64)."
fi

info "Installing xray binary → $XRAY_BIN"
install -m 755 "$LOCAL_BINARY" "$XRAY_BIN"
success "Binary installed"

# ── Config directory ───────────────────────────────────────────────────────────
info "Preparing config directory: $XRAY_CONFIG_DIR"
mkdir -p "$XRAY_CONFIG_DIR"

# If a config.json was passed as argument, copy it; otherwise use the one
# already placed there by install.sh
if [[ -n "${1:-}" && -f "$1" ]]; then
    info "Copying config: $1 → $XRAY_CONFIG"
    cp "$1" "$XRAY_CONFIG"
    chmod 600 "$XRAY_CONFIG"
    success "Config installed"
elif [[ -f "$XRAY_CONFIG" ]]; then
    info "Config already present at $XRAY_CONFIG — skipping copy."
else
    die "No config.json found.  Pass path as argument: install_xray.sh /path/to/config.json"
fi

# ── systemd service ────────────────────────────────────────────────────────────
info "Installing systemd service → $SERVICE_DEST"
if [[ ! -f "$SERVICE_SRC" ]]; then
    die "Service file not found: $SERVICE_SRC"
fi
cp "$SERVICE_SRC" "$SERVICE_DEST"
chmod 644 "$SERVICE_DEST"

systemctl daemon-reload
systemctl enable xray
systemctl restart xray

# ── Quick sanity check ─────────────────────────────────────────────────────────
sleep 2
if systemctl is-active --quiet xray; then
    success "xray service is running"
else
    echo -e "${RED}[WARN]${NC} xray service did not start — check logs:"
    echo "       journalctl -u xray -n 40 --no-pager"
    exit 1
fi
