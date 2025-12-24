#!/bin/bash

# ==============================================================================
# Automated Minecraft Server + Crafty Controller Installer
# Target OS: Ubuntu (20.04 / 22.04 / 24.04 recommended)
# Usage example:
# wget -O install.sh {url_of_this_script}
# chmod +x install.sh
# sudo ./minecraft-modded-server-setup-linux.sh "https://www.curseforge.com/api/v1/mods/924189/files/7268582/download"
# ==============================================================================

# Exit on error
set -e

# --- Configuration ---
CRAFTY_INSTALL_DIR="/var/opt/minecraft/crafty"
SERVER_IMPORT_DIR="${CRAFTY_INSTALL_DIR}/import"
MODPACK_URL="$1"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Helper Functions ---
log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_err() { echo -e "${RED}[ERROR]${NC} $1"; }

# --- 1. Pre-flight Checks ---

# Check for root
if [[ $EUID -ne 0 ]]; then
   log_err "This script must be run as root."
   exit 1
fi

# Check for Modpack URL argument
if [ -z "$MODPACK_URL" ]; then
    log_err "No modpack URL provided."
    echo "Usage: sudo ./install_mc_server.sh <DIRECT_DOWNLOAD_URL_TO_SERVER_PACK_ZIP>"
    exit 1
fi

# Check OS (Ubuntu detection)
if [ -f /etc/os-release ]; then
    . /etc/os-release
    if [[ "$ID" != "ubuntu" ]]; then
        log_warn "This script is optimized for Ubuntu. Detected: $ID. Proceeding, but errors may occur."
    else
        log_info "Detected OS: $NAME $VERSION_ID"
    fi
else
    log_err "Cannot detect OS. /etc/os-release not found."
    exit 1
fi

# --- 1.5 Interactive Configuration (Firewall & Ports) ---
echo ""
log_info "--- Configuration ---"

# Prompt for Minecraft Port
read -p "Enter Minecraft Server Port [25565]: " INPUT_PORT
MC_PORT=${INPUT_PORT:-25565}

# Prompt for Crafty Security
read -p "Restrict Crafty Web Panel (8443) to your IP only? [y/N]: " RESTRICT_CONFIRM
CRAFTY_ALLOW_IP=""
if [[ "$RESTRICT_CONFIRM" =~ ^[Yy]$ ]]; then
    while [[ -z "$CRAFTY_ALLOW_IP" ]]; do
        read -p "Enter your IP address: " CRAFTY_ALLOW_IP
    done
fi
echo ""

# --- 2. System Updates & Dependencies ---

log_info "Updating system packages..."
apt-get update && apt-get upgrade -y

log_info "Installing dependencies (Git, Python3, Unzip, UFW, etc)..."
apt-get install -y git python3 python3-dev python3-pip python3-venv software-properties-common unzip wget tar ufw

# Install multiple Java versions to ensure modpack compatibility
log_info "Installing Java 8, 17, and 21..."
# apt-get install is idempotent (skips if already installed)
apt-get install -y openjdk-8-jre-headless openjdk-17-jre-headless openjdk-21-jre-headless

# Verify Java installations
log_info "Java versions installed:"
update-java-alternatives --list

# --- 3. RAM Calculation ---

log_info "Calculating RAM allocation..."

# Get Total RAM in MB
TOTAL_RAM_MB=$(free -m | awk '/^Mem:/{print $2}')
# Reserve 1.5GB for OS + Crafty overhead
RESERVED_MB=1500
# Calculate Available
AVAILABLE_MB=$((TOTAL_RAM_MB - RESERVED_MB))

if [ $AVAILABLE_MB -le 1024 ]; then
    log_warn "Low memory detected! Available for Minecraft: ${AVAILABLE_MB}MB."
    ALLOCATION_MB=$((TOTAL_RAM_MB / 2)) # Fallback to 50% if extremely low
else
    ALLOCATION_MB=$AVAILABLE_MB
fi

ALLOCATION_GB=$(awk "BEGIN {printf \"%.1f\", $ALLOCATION_MB/1024}")
log_info "Total RAM: ${TOTAL_RAM_MB}MB"
log_info "Recommended Allocation for Minecraft: ${ALLOCATION_MB}MB (~${ALLOCATION_GB}GB)"

# --- 4. Firewall Setup (UFW) ---

log_info "Configuring Firewall (UFW)..."

# Set Default Policies (Idempotent)
ufw default deny incoming
ufw default allow outgoing

# Allow SSH (Critical to prevent lockout)
# 'ufw allow' checks if rule exists before adding, so this is safe to repeat.
ufw allow ssh
log_info "Firewall: Ensured SSH is allowed."

# Allow Minecraft Server Port
ufw allow "${MC_PORT}/tcp"
log_info "Firewall: Ensured Minecraft Server (Port ${MC_PORT}) is allowed."

# Allow Crafty Controller
if [[ -n "$CRAFTY_ALLOW_IP" ]]; then
    # If switching from global to specific IP, we should delete the global rule first if it exists
    ufw delete allow 8443/tcp
    ufw allow from "$CRAFTY_ALLOW_IP" to any port 8443 proto tcp

    log_info "Firewall: Allowed Crafty (Port 8443) from ${CRAFTY_ALLOW_IP} ONLY."
else
    ufw allow 8443/tcp
    log_info "Firewall: Allowed Crafty (Port 8443) from ANYWHERE."
fi

# Enable Firewall (Idempotent: "Firewall is active and enabled on system startup")
ufw --force enable
log_info "Firewall enabled/reloaded."

# --- 5. Install Crafty Controller ---

log_info "Setting up Crafty Controller..."

# Create user if not exists
if ! id "crafty" &>/dev/null; then
    useradd -r -m -d /var/opt/minecraft/crafty -s /bin/bash crafty
    log_info "User 'crafty' created."
else
    log_info "User 'crafty' already exists. Skipping creation."
fi

# Create directory structure
mkdir -p "$CRAFTY_INSTALL_DIR"
mkdir -p "$SERVER_IMPORT_DIR"

# Clone Crafty (Branch 4.x)
if [ -d "${CRAFTY_INSTALL_DIR}/crafty-4" ]; then
    log_info "Crafty directory already exists. Skipping clone to preserve data."
else
    log_info "Cloning Crafty 4 repository..."
    git clone -b master https://gitlab.com/crafty-controller/crafty-4.git "${CRAFTY_INSTALL_DIR}/crafty-4"
fi

# Fix permissions (Safe to re-run)
chown -R crafty:crafty "$CRAFTY_INSTALL_DIR"

# Install Crafty Dependencies (as crafty user)
# 'pip install' checks requirements and skips if satisfied, so this is safe to re-run.
log_info "Installing/Verifying Crafty Python dependencies..."
sudo -u crafty bash -c "cd ${CRAFTY_INSTALL_DIR}/crafty-4 && python3 -m venv .venv && source .venv/bin/activate && pip install --no-cache-dir -r requirements.txt"

# Create Systemd Service
# Overwriting this file is safe and ensures config consistency.
log_info "Updating Systemd service..."
cat > /etc/systemd/system/crafty.service <<EOF
[Unit]
Description=Crafty Controller
After=network.target

[Service]
User=crafty
Group=crafty
WorkingDirectory=${CRAFTY_INSTALL_DIR}/crafty-4
ExecStart=${CRAFTY_INSTALL_DIR}/crafty-4/.venv/bin/python3 ${CRAFTY_INSTALL_DIR}/crafty-4/main.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable crafty

# --- 6. Download and Prep Modpack ---

MODPACK_NAME=$(basename "$MODPACK_URL" .zip)
IMPORT_TARGET="${SERVER_IMPORT_DIR}/${MODPACK_NAME}"

# Check if modpack already downloaded to prevent overwrite/redownload
if [ -d "$IMPORT_TARGET" ] && [ "$(ls -A $IMPORT_TARGET)" ]; then
    log_warn "Modpack directory '$IMPORT_TARGET' already exists and is not empty."
    log_info "Skipping download and extraction to prevent overwriting existing files."
    log_info "If you want to force a re-download, delete the folder: $IMPORT_TARGET"
else
    log_info "Downloading Modpack from: $MODPACK_URL"
    TEMP_ZIP="/tmp/modpack_server.zip"
    wget -O "$TEMP_ZIP" "$MODPACK_URL"

    if [ ! -s "$TEMP_ZIP" ]; then
        log_err "Download failed or file is empty."
        exit 1
    fi

    mkdir -p "$IMPORT_TARGET"

    log_info "Extracting Modpack to import directory: $IMPORT_TARGET"
    unzip -o "$TEMP_ZIP" -d "$IMPORT_TARGET"
    rm "$TEMP_ZIP"
fi

# --- Auto-accept EULA ---
log_info "Checking for EULA..."
# Run this check regardless of download, to ensure EULA is set for existing installs too
if find "$IMPORT_TARGET" -name "eula.txt" | grep -q .; then
    find "$IMPORT_TARGET" -name "eula.txt" -exec sed -i 's/eula=false/eula=true/g' {} +
    log_info "Accepted EULA in existing file(s)."
else
    # Create one at the root if missing
    echo "eula=true" > "$IMPORT_TARGET/eula.txt"
    log_info "Created eula.txt with eula=true."
fi

# Fix permissions for the new files so Crafty can read/write them
chown -R crafty:crafty "$IMPORT_TARGET"
chmod -R 775 "$IMPORT_TARGET"

# --- 7. Finalize ---

log_info "Starting Crafty Controller..."
# If service is already running, this does nothing. If stopped, it starts.
systemctl start crafty

# Get IP Address
IP_ADDR=$(hostname -I | awk '{print $1}')

log_info "=========================================================="
log_info "Installation Complete!"
log_info "=========================================================="
echo -e "1. Access Crafty Controller at: ${GREEN}https://${IP_ADDR}:8443${NC}"
echo -e "2. Default Login: username: ${YELLOW}admin${NC}, password: (See below)"
echo -e "   Run this command to get the initial password:"
echo -e "   ${YELLOW}sudo cat ${CRAFTY_INSTALL_DIR}/crafty-4/app/config/default-creds.txt${NC}"
echo -e ""
echo -e "3. To setup your Modpack:"
echo -e "   - Login to Crafty and click 'Create New Server'."
echo -e "   - Select 'Import an Existing Server'."
echo -e "   - Set an arbitrary 'Server Name'."
echo -e "   - Set 'Server Path' to: ${GREEN}${IMPORT_TARGET}${NC}"
echo -e ""
echo -e "4. Files in your Server Path (Executable Search):"
echo -e "--------------------------------------------------"
# List files only, prevent clutter
ls -p "$IMPORT_TARGET" | grep -v /
echo -e "--------------------------------------------------"
echo -e ""
echo -e "5. Memory Settings:"
echo -e "   - Minimum Memory: ${YELLOW}${ALLOCATION_GB} GB${NC}"
echo -e "   - Maximum Memory: ${YELLOW}${ALLOCATION_GB} GB${NC}"
echo -e ""

# Auto-detect run.sh logic
RUN_SCRIPT="$IMPORT_TARGET/run.sh"
if [ -f "$RUN_SCRIPT" ]; then
    echo -e "6. ${YELLOW}Run Script Detected (Minecraft 1.17+):${NC}"
    echo -e "   - Set 'Server Executable' to: ${GREEN}run.sh${NC}"
    echo -e "   - Complete the import step."

    # Extract the unix_args.txt path (usually the second argument)
    # Pattern looks for @libraries...unix_args.txt
    FORGE_ARGS=$(grep -o '@libraries[^[:space:]]*unix_args.txt' "$RUN_SCRIPT" || echo "")

    if [ -n "$FORGE_ARGS" ]; then
        echo -e "   - ${YELLOW}Post-Import Configuration:${NC}"
        echo -e "     Go to ${GREEN}Config > Server Execution Command${NC} and set it to:"
        echo -e "     ${GREEN}java -Xms${ALLOCATION_MB}M -Xmx${ALLOCATION_MB}M ${FORGE_ARGS}${NC}"
        echo -e "     (This replaces user_jvm_args.txt with explicit RAM settings)"
    else
        echo -e "   - Note: run.sh found but could not auto-detect Forge arguments."
    fi
else
    echo -e "6. Server Executable:"
    echo -e "   - Select the main server jar (e.g., forge-1.12.2.jar) from the file list above."
fi
echo -e "=========================================================="
