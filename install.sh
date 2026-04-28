#!/bin/bash
set -Eeuo pipefail

REPO="https://github.com/gigiri33/sim.git"
BASE_DIR="/opt/seamless"
BASE_SERVICE="seamless"
DIR=""
SERVICE=""
INSTANCE_NUM=""
BOT_NAME=""

if [[ "${BASH_SOURCE[0]:-}" == /dev/fd/* ]] || [[ "${BASH_SOURCE[0]:-}" == /proc/*/fd/* ]]; then
  SCRIPT_DIR="$(pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

R='\033[31m'; G='\033[32m'; Y='\033[33m'; C='\033[36m'; M='\033[35m'; B='\033[1m'; W='\033[97m'; N='\033[0m'

# ─────────────────────────── header ───────────────────────────

header() {
  clear 2>/dev/null || true
  echo ""
  echo -e "${C}╔══════════════════════════════════════════════════════════════════════════╗${N}"
  echo -e "${C}║${N}          ${W}${B}⚡ Seamless — Telegram Config Sales Bot ⚡${N}                   ${C}║${N}"
  echo -e "${C}║${N}                                                                          ${C}║${N}"
  echo -e "${C}╠══════════════════════════════════════════════════════════════════════════╣${N}"

  echo -e "${C}║${N}   ${B}${G}GitHub:${N}    github.com/gigiri33/sim                                    ${C}║${N}"
  echo -e "${C}║${N}   ${B}${G}Developer:${N} t.me/EmadHabibnia                                          ${C}║${N}"
  echo -e "${C}║${N}   ${B}${G}Channel:${N}   @Emadhabibnia                                               ${C}║${N}"

  echo -e "${C}╚══════════════════════════════════════════════════════════════════════════╝${N}"
  echo ""
}

err()  { echo -e "${R}✗ $*${N}" >&2; exit 1; }
ok()   { echo -e "${G}✓ $*${N}"; }
info() { echo -e "${Y}➜ $*${N}"; }

on_error() { echo -e "${R}✗ Error on line ${BASH_LINENO[0]}${N}"; }


trap on_error ERR

check_root() {
  [[ $EUID -eq 0 ]] || err "Please run with sudo or as root"


}

ensure_safe_cwd() { cd / 2>/dev/null || true; }







install_prereqs() {
  info "Installing prerequisites..."
  apt-get update -y
  apt-get install -y git python3 python3-venv python3-pip curl iptables
}

# ─────────────────────── firewall (Plisio webhook port) ─────────────────────

open_firewall_port() {
  # Open inbound TCP port for Plisio webhook callbacks.
  # Tries (in order): ufw, firewalld, iptables. Silent on failure so install
  # never aborts because of firewall config.
  local PORT="$1"
  [[ -n "$PORT" ]] || return 0
  info "Opening firewall port ${PORT}/tcp for Plisio webhook…"

  # ufw (Debian/Ubuntu)
  if command -v ufw >/dev/null 2>&1; then
    ufw allow "${PORT}/tcp" >/dev/null 2>&1 || true
  fi

  # firewalld (RHEL/Fedora/CentOS)
  if command -v firewall-cmd >/dev/null 2>&1; then
    firewall-cmd --permanent --add-port="${PORT}/tcp" >/dev/null 2>&1 || true
    firewall-cmd --reload >/dev/null 2>&1 || true
  fi

  # iptables (always, as final fallback)
  if command -v iptables >/dev/null 2>&1; then
    if ! iptables -C INPUT -p tcp --dport "$PORT" -j ACCEPT >/dev/null 2>&1; then
      iptables -I INPUT -p tcp --dport "$PORT" -j ACCEPT >/dev/null 2>&1 || true
    fi
    # Persist rule across reboots if iptables-persistent / netfilter-persistent is installed
    if command -v netfilter-persistent >/dev/null 2>&1; then
      netfilter-persistent save >/dev/null 2>&1 || true
    elif [[ -d /etc/iptables ]]; then
      iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
    fi
  fi
  ok "Firewall: TCP ${PORT} allowed (where supported)."
}

# ─────────────────────── helpers for name/time ───────────────────────────

get_bot_name() {
  local d="${BASE_DIR}-${1}"
  if [[ -f "$d/.bot_name" ]]; then
    cat "$d/.bot_name"
  else
    echo "Bot #${1}"
  fi
}

save_bot_name() {
  echo "$BOT_NAME" > "$DIR/.bot_name"
}

record_update_time() {
  date '+%Y-%m-%d %H:%M:%S' > "$DIR/.last_update"
}

get_last_update() {
  local d="${BASE_DIR}-${1}"
  if [[ -f "$d/.last_update" ]]; then
    cat "$d/.last_update"
  else
    echo "Never"
  fi
}

get_service_status() {
  local svc="${BASE_SERVICE}-${1}"
  if systemctl is-active "$svc" >/dev/null 2>&1; then
    echo -e "${G}🟢 Online${N}"
  else
    echo -e "${R}🔴 Offline${N}"
  fi
}

get_autoupdate_status_label() {
  local svc="${BASE_SERVICE}-${1}-autoupdate"
  if systemctl is-active "${svc}.timer" >/dev/null 2>&1; then
    echo -e "${G}[ON]${N}"
  else
    echo -e "${R}[OFF]${N}"
  fi
}

# ─────────────────────────── repo / venv ───────────────────────────

clone_or_update_repo() {
  info "Downloading Seamless..."

  mkdir -p "$DIR"

  if [[ -d "$DIR/.git" ]]; then
    info "Repository exists. Updating..."
    cd "$DIR"
    git fetch --all --prune
    git reset --hard origin/main
  else
    rm -rf "$DIR"
    mkdir -p "$DIR"
    git clone "$REPO" "$DIR"
    cd "$DIR"
  fi
  [[ -f "$DIR/main.py" ]]          || err "main.py not found after download."

  [[ -f "$DIR/requirements.txt" ]] || err "requirements.txt not found after download."
  record_update_time
}

setup_venv() {
  info "Setting up Python environment..."
  [[ -d "$DIR/venv" ]] || python3 -m venv "$DIR/venv"



  "$DIR/venv/bin/pip" install --upgrade pip wheel
  "$DIR/venv/bin/pip" install -r "$DIR/requirements.txt"
}

# ─────────────────────────── configure ───────────────────────────

configure_env() {
  echo ""
  echo -e "${C}╔══════════════════════════════════════════════════════════════════════════╗${N}"
  echo -e "${C}║${N}              ${B}${W}⚙️  Bot Configuration: ${BOT_NAME}${N}"
  echo -e "${C}╚══════════════════════════════════════════════════════════════════════════╝${N}"
  echo ""

  echo -e "${Y}📌 Get your bot token from ${B}@BotFather${N}${Y} on Telegram.${N}"
  echo ""
  read -r -p "$(echo -e "${B}🔑 Telegram Bot Token: ${N}")" INPUT_TOKEN
  INPUT_TOKEN="${INPUT_TOKEN// /}"
  [[ -n "$INPUT_TOKEN" ]]                      || err "Token cannot be empty"
  [[ "$INPUT_TOKEN" =~ ^[0-9]+:.+$ ]]         || err "Invalid token format. Example: 123456789:ABCdef..."

  echo ""
  echo -e "${Y}📌 Send a message to ${B}@userinfobot${N}${Y} on Telegram to get your Chat ID.${N}"
  echo ""
  read -r -p "$(echo -e "${B}Admin Chat ID (numeric): ${N}")" INPUT_ADMIN
  INPUT_ADMIN="${INPUT_ADMIN// /}"
  [[ "$INPUT_ADMIN" =~ ^-?[0-9]+$ ]] || err "Admin ID must be numeric"

  echo ""
  read -r -p "$(echo -e "${B}📂 Database name [Seamless.db]: ${N}")" INPUT_DB
  INPUT_DB="${INPUT_DB:-Seamless.db}"

  # ── Plisio webhook port: unique per instance (5050 + (instance-1)) ──────
  local PLISIO_PORT=$((5050 + INSTANCE_NUM - 1))

  cat > "$DIR/.env" << ENVEOF
BOT_TOKEN=${INPUT_TOKEN}
ADMIN_IDS=${INPUT_ADMIN}
DB_NAME=${INPUT_DB}
PLISIO_WEBHOOK_PORT=${PLISIO_PORT}
ENVEOF
  chmod 600 "$DIR/.env"
  echo ""
  ok "Configuration saved to $DIR/.env"
  echo -e "${Y}🌐 Plisio webhook port for this bot: ${B}${PLISIO_PORT}${N}"

  # Open this port on the firewall so Plisio's IPN can reach the bot
  open_firewall_port "$PLISIO_PORT"
}

configure_iran_worker() {
  echo ""
  echo -e "${C}╔══════════════════════════════════════════════════════════════════════════╗${N}"
  echo -e "${C}║${N}        ${B}${W}🇮🇷  Iran Worker (3x-ui) Configuration — ${BOT_NAME}${N}"
  echo -e "${C}╚══════════════════════════════════════════════════════════════════════════╝${N}"
  echo ""

  read -r -p "$(echo -e "${B}🌐 Panel IP (default 127.0.0.1): ${N}")" INPUT_PANEL_IP
  INPUT_PANEL_IP="${INPUT_PANEL_IP:-127.0.0.1}"

  read -r -p "$(echo -e "${B}🔌 Panel port (default 2053): ${N}")" INPUT_PANEL_PORT
  INPUT_PANEL_PORT="${INPUT_PANEL_PORT:-2053}"
  [[ "$INPUT_PANEL_PORT" =~ ^[0-9]+$ ]] || err "Port must be numeric"

  read -r -p "$(echo -e "${B}📄 Path (optional, e.g. /xui — press Enter to skip): ${N}")" INPUT_PATCH
  INPUT_PATCH="${INPUT_PATCH:-}"

  read -r -p "$(echo -e "${B}👤 Panel username: ${N}")" INPUT_PANEL_USER
  [[ -n "$INPUT_PANEL_USER" ]] || err "Username cannot be empty"

  read -r -s -p "$(echo -e "${B}🔑 Panel password: ${N}")" INPUT_PANEL_PASS
  echo ""
  [[ -n "$INPUT_PANEL_PASS" ]] || err "Password cannot be empty"

  read -r -p "$(echo -e "${B}🆔 Inbound ID (default 1): ${N}")" INPUT_INBOUND_ID
  INPUT_INBOUND_ID="${INPUT_INBOUND_ID:-1}"
  [[ "$INPUT_INBOUND_ID" =~ ^[0-9]+$ ]] || err "Inbound ID must be numeric"

  read -r -p "$(echo -e "${B}🔐 Worker API Key (min 16 chars; press Enter to auto-generate): ${N}")" INPUT_WORKER_KEY
  if [[ -z "$INPUT_WORKER_KEY" ]]; then
    INPUT_WORKER_KEY=$(tr -dc 'A-Za-z0-9' </dev/urandom 2>/dev/null | head -c 32 || openssl rand -hex 16)
  fi
  [[ ${#INPUT_WORKER_KEY} -ge 16 ]] || err "API key must be at least 16 characters"

  read -r -p "$(echo -e "${B}🌍 Bot API URL (e.g. http://foreign-server:8080): ${N}")" INPUT_API_URL
  [[ -n "$INPUT_API_URL" ]] || err "Bot API URL cannot be empty"

  read -r -p "$(echo -e "${B}⏱ Poll interval (seconds, default 10): ${N}")" INPUT_POLL
  INPUT_POLL="${INPUT_POLL:-10}"
  [[ "$INPUT_POLL" =~ ^[0-9]+$ ]] || err "Poll interval must be numeric"

  cat > "$DIR/config.env" << ENVEOF
BOT_API_URL=${INPUT_API_URL}
WORKER_API_KEY=${INPUT_WORKER_KEY}
PANEL_IP=${INPUT_PANEL_IP}
PANEL_PORT=${INPUT_PANEL_PORT}
PANEL_PATCH=${INPUT_PATCH}
PANEL_USERNAME=${INPUT_PANEL_USER}
PANEL_PASSWORD=${INPUT_PANEL_PASS}
INBOUND_ID=${INPUT_INBOUND_ID}
POLL_INTERVAL=${INPUT_POLL}
PROTOCOL=vless
ENVEOF
  chmod 600 "$DIR/config.env"
  echo ""
  ok "Worker configuration saved to $DIR/config.env"
  echo -e "${Y}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
  echo -e "${B}${W}   ⚠️  Save this API Key for the bot admin panel:${N}"
  echo -e "   ${B}${G}WORKER_API_KEY = ${INPUT_WORKER_KEY}${N}"
  echo -e "${Y}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${N}"
  echo ""
  read -r -p "Press Enter to continue..."
}

# ─────────────────────────── systemd ───────────────────────────

create_systemd_service() {
  info "Creating systemd service for ${SERVICE}..."
  cat > "/etc/systemd/system/$SERVICE.service" << EOF
[Unit]
Description=Seamless Telegram Bot — ${BOT_NAME}
After=network.target
StartLimitIntervalSec=0

[Service]
Type=simple
WorkingDirectory=${DIR}
EnvironmentFile=${DIR}/.env
ExecStart=${DIR}/venv/bin/python ${DIR}/main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "$SERVICE" >/dev/null 2>&1 || true
}


start_service() {
  systemctl restart "$SERVICE"
  echo ""
  echo -e "${G}╔══════════════════════════════════════════════════════════════════════════╗${N}"
  echo -e "${G}║${N}        ${B}${G}✅  ${BOT_NAME} installed and started!${N}                          ${G}║${N}"
  echo -e "${G}╚══════════════════════════════════════════════════════════════════════════╝${N}"
  echo ""
  systemctl status "$SERVICE" --no-pager -l || true
}

# ─────────────────────────── auto-update ───────────────────────────

enable_auto_update() {
  ensure_safe_cwd
  [[ -d "$DIR/.git" ]] || err "Bot not installed. Please install first."

  local AUTOUPDATE_SCRIPT="$DIR/auto_update.sh"
  local AUTOUPDATE_SVC="${SERVICE}-autoupdate"

  info "Creating auto-update script..."
  cat > "$AUTOUPDATE_SCRIPT" << EOFSCRIPT
#!/bin/bash
cd "$DIR" || exit 1
git fetch --all --prune 2>/dev/null
LOCAL=\$(git rev-parse HEAD)
REMOTE=\$(git rev-parse origin/main)
if [[ "\$LOCAL" != "\$REMOTE" ]]; then
  echo "\$(date '+%Y-%m-%d %H:%M:%S') — Update found (\${LOCAL:0:7} → \${REMOTE:0:7}), updating..."
  git reset --hard origin/main
  "$DIR/venv/bin/pip" install -r "$DIR/requirements.txt" -q
  date '+%Y-%m-%d %H:%M:%S' > "$DIR/.last_update"
  systemctl restart "$SERVICE"
  echo "\$(date '+%Y-%m-%d %H:%M:%S') — Updated and restarted $SERVICE"
else
  echo "\$(date '+%Y-%m-%d %H:%M:%S') — Already up to date (\${LOCAL:0:7})"
fi
EOFSCRIPT
  chmod +x "$AUTOUPDATE_SCRIPT"

  cat > "/etc/systemd/system/${AUTOUPDATE_SVC}.service" << EOF
[Unit]
Description=Seamless Auto Update — ${BOT_NAME}
After=network.target

[Service]
Type=oneshot
ExecStart=$AUTOUPDATE_SCRIPT
StandardOutput=append:$DIR/autoupdate.log
StandardError=append:$DIR/autoupdate.log
EOF

  cat > "/etc/systemd/system/${AUTOUPDATE_SVC}.timer" << EOF
[Unit]
Description=Seamless Auto Update Timer — ${BOT_NAME}

[Timer]
OnCalendar=minutely
Persistent=true

[Install]
WantedBy=timers.target
EOF

  systemctl daemon-reload
  systemctl enable "${AUTOUPDATE_SVC}.timer" >/dev/null 2>&1
  systemctl start  "${AUTOUPDATE_SVC}.timer"
  echo ""
  ok "Auto-update enabled for ${BOT_NAME} (checked every minute)"
  echo -e "${Y}Log: $DIR/autoupdate.log${N}"
  echo ""
}

disable_auto_update() {
  ensure_safe_cwd
  local AUTOUPDATE_SVC="${SERVICE}-autoupdate"
  systemctl stop    "${AUTOUPDATE_SVC}.timer"   2>/dev/null || true
  systemctl disable "${AUTOUPDATE_SVC}.timer"   2>/dev/null || true
  systemctl stop    "${AUTOUPDATE_SVC}.service" 2>/dev/null || true
  rm -f "/etc/systemd/system/${AUTOUPDATE_SVC}.timer"
  rm -f "/etc/systemd/system/${AUTOUPDATE_SVC}.service"
  rm -f "$DIR/auto_update.sh"
  systemctl daemon-reload
  ok "Auto-update disabled for ${BOT_NAME}."
}

toggle_auto_update() {
  local AUTOUPDATE_SVC="${SERVICE}-autoupdate"
  if systemctl is-active "${AUTOUPDATE_SVC}.timer" >/dev/null 2>&1; then
    disable_auto_update
  else
    enable_auto_update
  fi
  read -r -p "Press Enter to continue..."
}

# ─────────────────────────── install / update / remove ───────────────────────────

install_bot() {
  ensure_safe_cwd
  install_prereqs
  clone_or_update_repo
  save_bot_name
  setup_venv
  configure_env
  create_systemd_service
  # auto-update by default
  enable_auto_update
  start_service
}

update_bot() {
  ensure_safe_cwd
  [[ -d "$DIR/.git" ]] || err "Not installed. Please install first."
  info "Updating ${BOT_NAME}..."
  clone_or_update_repo
  setup_venv
  systemctl restart "$SERVICE"
  ok "Update of ${BOT_NAME} completed!"
  echo ""
  echo -e "${Y}ℹ️  License Notice:${N}"
  echo -e "${Y}   If this is an existing bot without a license, it will run in${N}"
  echo -e "${Y}   LIMITED MODE. Use /license_status inside the bot to activate.${N}"
}

edit_config() {
  ensure_safe_cwd
  [[ -f "$DIR/.env" ]] || err "Config file not found. Please install first."
  nano "$DIR/.env"
  systemctl restart "$SERVICE"
  ok "Settings saved and bot restarted!"
}

remove_bot() {
  ensure_safe_cwd
  read -r -p "Are you sure you want to remove ${BOT_NAME}? (yes/no): " confirm
  [[ "$confirm" == "yes" ]] || { info "Cancelled"; return; }

  for svc in "$SERVICE"; do
    systemctl stop    "$svc" 2>/dev/null || true
    systemctl disable "$svc" 2>/dev/null || true
    rm -f "/etc/systemd/system/${svc}.service"
  done
  systemctl stop    "${SERVICE}-autoupdate.timer"   2>/dev/null || true
  systemctl disable "${SERVICE}-autoupdate.timer"   2>/dev/null || true
  systemctl stop    "${SERVICE}-autoupdate.service" 2>/dev/null || true
  rm -f "/etc/systemd/system/${SERVICE}-autoupdate.timer"
  rm -f "/etc/systemd/system/${SERVICE}-autoupdate.service"
  systemctl daemon-reload
  rm -rf "$DIR"
  ok "${BOT_NAME} has been completely removed"
}



# ─────────────────────────── BULK OPERATIONS ───────────────────────────

all_instances() {
  local list=()
  for d in /opt/seamless-*/; do
    [[ -d "$d" ]] || continue
    local num; num="$(basename "$d" | sed 's/seamless-//')"
    [[ "$num" =~ ^[0-9]+$ ]] && list+=("$num")
  done
  echo "${list[@]:-}"
}

bulk_update_all() {
  local instances; instances="$(all_instances)"
  [[ -n "$instances" ]] || { echo -e "${Y}No installed bots found.${N}"; read -r -p "Enter..."; return; }
  for num in $instances; do
    DIR="${BASE_DIR}-${num}"
    SERVICE="${BASE_SERVICE}-${num}"
    BOT_NAME="$(get_bot_name "$num")"
    echo ""
    echo -e "${C}━━━ Updating ${BOT_NAME} (instance ${num}) ━━━${N}"
    [[ -d "$DIR/.git" ]] || { echo -e "${R}✗ Not installed, skipping.${N}"; continue; }
    clone_or_update_repo
    setup_venv
    systemctl restart "$SERVICE" 2>/dev/null || true
    ok "${BOT_NAME} updated"
  done
  echo ""
  read -r -p "Press Enter to continue..."
}

bulk_enable_autoupdate() {
  local instances; instances="$(all_instances)"
  [[ -n "$instances" ]] || { echo -e "${Y}No installed bots found.${N}"; read -r -p "Enter..."; return; }
  for num in $instances; do
    DIR="${BASE_DIR}-${num}"
    SERVICE="${BASE_SERVICE}-${num}"
    BOT_NAME="$(get_bot_name "$num")"
    echo ""
    echo -e "${C}━━━ Enabling auto-update for ${BOT_NAME} ━━━${N}"
    [[ -d "$DIR/.git" ]] || { echo -e "${R}✗ Not installed, skipping.${N}"; continue; }
    enable_auto_update
  done
  echo ""
  read -r -p "Press Enter to continue..."
}

bulk_disable_autoupdate() {
  local instances; instances="$(all_instances)"
  [[ -n "$instances" ]] || { echo -e "${Y}No installed bots found.${N}"; read -r -p "Enter..."; return; }
  for num in $instances; do
    DIR="${BASE_DIR}-${num}"
    SERVICE="${BASE_SERVICE}-${num}"
    BOT_NAME="$(get_bot_name "$num")"
    echo ""
    echo -e "${C}━━━ Disabling auto-update for ${BOT_NAME} ━━━${N}"
    disable_auto_update
  done
  echo ""
  read -r -p "Press Enter to continue..."
}

bulk_restart_all() {
  local instances; instances="$(all_instances)"
  [[ -n "$instances" ]] || { echo -e "${Y}No installed bots found.${N}"; read -r -p "Enter..."; return; }
  for num in $instances; do
    local svc="${BASE_SERVICE}-${num}"
    local name; name="$(get_bot_name "$num")"
    systemctl restart "$svc" 2>/dev/null && ok "Restarted: ${name}" || echo -e "${R}✗ Error: ${name}${N}"
  done
  echo ""
  read -r -p "Press Enter to continue..."
}

bulk_start_all() {
  local instances; instances="$(all_instances)"
  [[ -n "$instances" ]] || { echo -e "${Y}No installed bots found.${N}"; read -r -p "Enter..."; return; }
  for num in $instances; do
    local svc="${BASE_SERVICE}-${num}"
    local name; name="$(get_bot_name "$num")"
    systemctl start "$svc" 2>/dev/null && ok "Started: ${name}" || echo -e "${R}✗ Error: ${name}${N}"
  done
  echo ""
  read -r -p "Press Enter to continue..."
}

bulk_stop_all() {
  local instances; instances="$(all_instances)"
  [[ -n "$instances" ]] || { echo -e "${Y}No installed bots found.${N}"; read -r -p "Enter..."; return; }
  for num in $instances; do
    local svc="${BASE_SERVICE}-${num}"
    local name; name="$(get_bot_name "$num")"
    systemctl stop "$svc" 2>/dev/null && ok "Stopped: ${name}" || echo -e "${R}✗ Error: ${name}${N}"
  done
  echo ""
  read -r -p "Press Enter to continue..."
}

bulk_remove_all() {
  local instances; instances="$(all_instances)"
  [[ -n "$instances" ]] || { echo -e "${Y}No installed bots found.${N}"; read -r -p "Enter..."; return; }
  echo -e "${R}⚠️  This will remove ALL bots!${N}"
  read -r -p "Type DELETE ALL to confirm: " confirm
  [[ "$confirm" == "DELETE ALL" ]] || { info "Cancelled"; read -r -p "Press Enter to continue..."; return; }
  for num in $instances; do
    DIR="${BASE_DIR}-${num}"
    SERVICE="${BASE_SERVICE}-${num}"
    BOT_NAME="$(get_bot_name "$num")"
    echo ""
    echo -e "${C}━━━ Removing ${BOT_NAME} ━━━${N}"
    systemctl stop    "$SERVICE" 2>/dev/null || true
    systemctl disable "$SERVICE" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE}.service"
    systemctl stop    "${SERVICE}-autoupdate.timer"   2>/dev/null || true
    systemctl disable "${SERVICE}-autoupdate.timer"   2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE}-autoupdate.timer"
    rm -f "/etc/systemd/system/${SERVICE}-autoupdate.service"
    rm -rf "$DIR"
    ok "${BOT_NAME} removed"
  done
  systemctl daemon-reload
  echo ""
  read -r -p "Press Enter to continue..."
}

# ─────────────────────────── menus ───────────────────────────

list_instances_table() {
  local found=0
  echo -e "${C}┌────┬────────────────────────────┬───────────────┬──────────────────────┐${N}"
  echo -e "${C}│${N} ${B}${W}#${N}  ${C}│${N} ${B}${W}Bot Name${N}                    ${C}│${N} ${B}${W}Status${N}         ${C}│${N} ${B}${W}Last Update${N}          ${C}│${N}"
  echo -e "${C}├────┼────────────────────────────┼───────────────┼──────────────────────┤${N}"
  for d in /opt/seamless-*/; do
    [[ -d "$d" ]] || continue
    local num; num="$(basename "$d" | sed 's/seamless-//')"
    [[ "$num" =~ ^[0-9]+$ ]] || continue
    local name; name="$(get_bot_name "$num")"
    local svc="${BASE_SERVICE}-${num}"
    local status_raw status_str
    if systemctl is-active "$svc" >/dev/null 2>&1; then
      status_str="${G}🟢 Online   ${N}"
    else
      status_str="${R}🔴 Offline${N}"
    fi
    local last; last="$(get_last_update "$num")"
    printf "${C}│${N} %-2s ${C}│${N} %-26s ${C}│${N} " "$num" "$name"
    echo -ne "$status_str"
    printf " ${C}│${N} %-20s ${C}│${N}\n" "$last"
    found=1
  done
  if [[ $found -eq 0 ]]; then
    echo -e "${C}│${N}               ${Y}No bots installed${N}                              ${C}│${N}"
  fi
  echo -e "${C}└────┴────────────────────────────┴───────────────┴──────────────────────┘${N}"
  echo ""
}

show_global_menu() {
  echo -e "${C}┌──────────────────────────────────────────┐${N}"
  echo -e "${C}│${N}       ${B}${W}🌐 Main Menu — Seamless${N}           ${C}│${N}"
  echo -e "${C}├──────────────────────────────────────────┤${N}"
  echo -e "${C}│${N}  ${B}${G}m)${N} 🤖 Manage a bot (select number)    ${C}│${N}"
  echo -e "${C}├──────────────────────────────────────────┤${N}"
  echo -e "${C}│${N}  ${B}${Y}1)${N} 🔄 Update all bots                    ${C}│${N}"
  echo -e "${C}│${N}  ${B}${Y}2)${N} ⚡ Enable auto-update for all         ${C}│${N}"
  echo -e "${C}│${N}  ${B}${Y}3)${N} 🔕 Disable auto-update for all     ${C}│${N}"
  echo -e "${C}│${N}  ${B}${Y}4)${N} 🔁 Restart all bots                     ${C}│${N}"
  echo -e "${C}│${N}  ${B}${Y}5)${N} ▶️  Start all bots                     ${C}│${N}"
  echo -e "${C}│${N}  ${B}${Y}6)${N} ⏹️  Stop all bots                     ${C}│${N}"
  echo -e "${C}│${N}  ${B}${R}7)${N} 🗑️  Remove all bots                          ${C}│${N}"
  echo -e "${C}├──────────────────────────────────────────┤${N}"
  echo -e "${C}│${N}  ${B}${R}0)${N} 🚪 Exit                            ${C}│${N}"
  echo -e "${C}└──────────────────────────────────────────┘${N}"
  echo ""
}

show_bot_header() {
  local au_status; au_status="$(get_autoupdate_status_label "$INSTANCE_NUM")"
  local bot_status; bot_status="$(get_service_status "$INSTANCE_NUM")"
  local last_upd; last_upd="$(get_last_update "$INSTANCE_NUM")"
  echo -e "${C}╔══════════════════════════════════════════════════════════════════════════╗${N}"
  echo -e "${C}║${N}  🤖 ${B}${W}${BOT_NAME}${N}  (instance ${INSTANCE_NUM})                                        ${C}║${N}"
  echo -e "${C}║${N}  Status: $bot_status   │  Auto-update: $au_status   │  Last update: ${W}${last_upd}${N}  ${C}║${N}"
  echo -e "${C}╚══════════════════════════════════════════════════════════════════════════╝${N}"
  echo ""
}

show_bot_menu() {
  local au_label; au_label="$(get_autoupdate_status_label "$INSTANCE_NUM")"
  echo -e "${C}┌──────────────────────────────────────┐${N}"
  echo -e "${C}│${N}  ${B}${G}1)${N} 📦 Install / Reinstall                     ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}2)${N} 🔄 Update from GitHub                 ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}3)${N} ✏️  Edit settings (.env)            ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}4)${N} ▶️  Start                                       ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}5)${N} ⏹️  Stop                                       ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}6)${N} 🔁 Restart                                       ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}7)${N} 📜 Live log                                      ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}8)${N} 📊 Service status                             ${C}│${N}"
  echo -e "${C}│${N}  ${B}${G}9)${N} 🗑️  Remove this bot                          ${C}│${N}"
  echo -e "${C}│${N}  ${B}${C}a)${N} ⚡ Auto-update: $au_label           ${C}│${N}"
  echo -e "${C}│${N}  ${B}${C}u)${N} 📋 Auto-update log                    ${C}│${N}"
  echo -e "${C}│${N}  ${B}${R}b)${N} 🔙 Back to main menu               ${C}│${N}"
  echo -e "${C}└──────────────────────────────────────┘${N}"
  echo ""
}

# ─────────────────────────── instance selection ───────────────────────────

select_instance() {
  echo ""
  list_instances_table
  echo -e "${Y}📌 Enter the bot number (e.g. 1, 2, 3 ...).${N}"
  echo -e "${Y}   Each number is a separate bot with its own settings and database.${N}"
  echo ""
  read -r -p "$(echo -e "${B}🔢 Bot number: ${N}")" INSTANCE_NUM
  INSTANCE_NUM="${INSTANCE_NUM// /}"
  [[ "$INSTANCE_NUM" =~ ^[0-9]+$ ]] || err "Number must be a positive integer (e.g. 1, 2, 3)"
  [[ "$INSTANCE_NUM" -ge 1 ]]       || err "Number must be >= 1"

  DIR="${BASE_DIR}-${INSTANCE_NUM}"
  SERVICE="${BASE_SERVICE}-${INSTANCE_NUM}"

  # If new instance → ask for a name
  if [[ ! -f "$DIR/.bot_name" ]]; then
    echo ""
    echo -e "${Y}📌 This is a new bot. Enter a name for easy identification.${N}"
    read -r -p "$(echo -e "${B}📛 Bot name (e.g. "Main Sales Bot"): ${N}")" INPUT_BOT_NAME
    INPUT_BOT_NAME="${INPUT_BOT_NAME:-Bot #${INSTANCE_NUM}}"
    BOT_NAME="$INPUT_BOT_NAME"
    mkdir -p "$DIR"
    save_bot_name
  else
    BOT_NAME="$(get_bot_name "$INSTANCE_NUM")"
  fi

  echo ""
  ok "Bot selected: ${B}${BOT_NAME}${N}  (dir: $DIR  service: $SERVICE)"
  echo ""
}

# ─────────────────────────── main loops ───────────────────────────

bot_loop() {
  while true; do
    header
    show_bot_header
    show_bot_menu

    read -r -p "$(echo -e "${C}${BOT_NAME}${N} ${B}➜${N} option ${W}[0-9/a/u/b]${N}: ")" choice

    case "${choice:-}" in
      1) install_bot; read -r -p "Enter...";;
      2) update_bot;  read -r -p "Enter...";;
      3) edit_config ;;
      4) systemctl start   "$SERVICE" 2>/dev/null && ok "Started: ${BOT_NAME}";   read -r -p "Enter...";;
      5) systemctl stop    "$SERVICE" 2>/dev/null && ok "Stopped: ${BOT_NAME}";  read -r -p "Enter...";;
      6) systemctl restart "$SERVICE" 2>/dev/null && ok "Restarted: ${BOT_NAME}"; read -r -p "Enter...";;
      7) echo -e "${Y}Press Ctrl+C to exit log${N}"; sleep 1; journalctl -u "$SERVICE" -f;;
      8) systemctl status "$SERVICE" --no-pager -l; read -r -p "Enter...";;
      9) remove_bot; read -r -p "Enter..."; return;;
      a) toggle_auto_update ;;
      u) echo -e "${Y}Press Ctrl+C to exit log${N}"; sleep 1
         tail -f "$DIR/autoupdate.log" 2>/dev/null || echo -e "${R}Log file not found.${N}"
         read -r -p "Enter...";;
      b) return;;
      *) echo -e "${R}Invalid option${N}"; sleep 1;;
    esac
  done
}

main() {

  [[ -t 0 ]] || exec < /dev/tty
  check_root
  ensure_safe_cwd


  while true; do
    header
    list_instances_table
    show_global_menu


    read -r -p "$(echo -e "${C}Seamless${N} ${B}➜${N} option ${W}[m/1-7/0]${N}: ")" choice

    case "${choice:-}" in
      m)
        select_instance
        bot_loop
        ;;
      1) header; bulk_update_all ;;
      2) header; bulk_enable_autoupdate ;;
      3) header; bulk_disable_autoupdate ;;
      4) header; bulk_restart_all ;;
      5) header; bulk_start_all ;;
      6) header; bulk_stop_all ;;
      7) header; bulk_remove_all ;;

      0) echo "Goodbye!"; exit 0;;
      *) echo -e "${R}Invalid option${N}"; sleep 1;;
    esac
  done
}

main "$@"