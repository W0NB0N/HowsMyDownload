#!/usr/bin/env bash
# ==============================================================================
# Download Notifs — Oracle Cloud VM Automated Provisioning Script
# Target OS: Ubuntu 22.04 / 24.04 LTS (ARM64 VM.Standard.A1.Flex or x86_64)
# ==============================================================================

set -euo pipefail

# Text formatting
GREEN='\033[0;32m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${PURPLE}"
cat << "EOF"
==========================================================
    $ notifs // oracle_vm_automated_setup
==========================================================
EOF
echo -e "${NC}"

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR] This script must be run as root or with sudo.${NC}"
    exit 1
fi

DEPLOY_DIR="/opt/notifs"
CURRENT_USER="${SUDO_USER:-ubuntu}"

echo -e "${CYAN}[1/7] Updating system packages and installing prerequisites...${NC}"
apt-get update && apt-get upgrade -y
apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    ufw \
    iptables-persistent \
    netfilter-persistent \
    nginx \
    certbot \
    python3-certbot-nginx

echo -e "${CYAN}[2/7] Configuring Oracle Cloud firewall & iptables rules...${NC}"
# Oracle Cloud Ubuntu images include strict default iptables rules that reject incoming traffic
# on ports 80 and 443 even if VCN Security Lists are open. We explicitly allow them.
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT || iptables -A INPUT -p tcp --dport 80 -j ACCEPT
iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT || iptables -A INPUT -p tcp --dport 443 -j ACCEPT
netfilter-persistent save

# Configure UFW
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'
ufw --force enable

echo -e "${CYAN}[3/7] Installing Docker CE and Docker Compose plugin...${NC}"
if ! command -v docker &> /dev/null; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg --yes
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    usermod -aG docker "$CURRENT_USER"
    echo -e "${GREEN}✓ Docker installed successfully.${NC}"
else
    echo -e "${GREEN}✓ Docker is already installed.${NC}"
fi

echo -e "${CYAN}[4/7] Setting up deployment directory at ${DEPLOY_DIR}...${NC}"
mkdir -p "${DEPLOY_DIR}/deploy"
mkdir -p "${DEPLOY_DIR}/server"
mkdir -p "/var/www/certbot"

# Copy local repository files if running from repo root
if [ -f "./pyproject.toml" ]; then
    cp -r ./pyproject.toml "${DEPLOY_DIR}/"
    cp -r ./server/* "${DEPLOY_DIR}/server/"
    cp -r ./deploy/* "${DEPLOY_DIR}/deploy/"
fi

# Set up .env template if missing
if [ ! -f "${DEPLOY_DIR}/deploy/.env" ]; then
    if [ -f "${DEPLOY_DIR}/deploy/env.example" ]; then
        cp "${DEPLOY_DIR}/deploy/env.example" "${DEPLOY_DIR}/deploy/.env"
    else
        cat << 'EOF' > "${DEPLOY_DIR}/deploy/.env"
STORE_TYPE=firestore
NOTIFIER_TYPE=fcm
REQUIRE_AUTH=true
GOOGLE_APPLICATION_CREDENTIALS=/app/service-account.json
PORT=8000
HOST=0.0.0.0
CORS_ORIGINS=*
EOF
    fi
    echo -e "${YELLOW}Created template .env at ${DEPLOY_DIR}/deploy/.env.${NC}"
fi

chown -R "$CURRENT_USER:$CURRENT_USER" "${DEPLOY_DIR}"

echo -e "${CYAN}[5/7] Installing Systemd Service for notifs-api...${NC}"
if [ -f "${DEPLOY_DIR}/deploy/systemd/notifs-api.service" ]; then
    cp "${DEPLOY_DIR}/deploy/systemd/notifs-api.service" /etc/systemd/system/notifs-api.service
    systemctl daemon-reload
    systemctl enable notifs-api.service
    echo -e "${GREEN}✓ Systemd unit notifs-api.service installed.${NC}"
fi

echo -e "${CYAN}[6/7] Nginx Reverse Proxy Setup...${NC}"
cat << 'EOF' > /etc/nginx/sites-available/notifs.conf
# Temporary HTTP config for initial setup and Certbot verification
server {
    listen 80;
    listen [::]:80;
    server_name _;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/notifs.conf /etc/nginx/sites-enabled/notifs.conf
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo -e "${CYAN}[7/7] Checking for Firebase Service Account Key...${NC}"
if [ -f "${DEPLOY_DIR}/deploy/service-account.json" ]; then
    echo -e "${GREEN}✓ service-account.json found.${NC}"
    echo -e "${GREEN}Starting notifs-api service...${NC}"
    systemctl restart notifs-api.service || true
else
    echo -e "${YELLOW}================================================================${NC}"
    echo -e "${YELLOW}[ACTION REQUIRED] Firebase Service Account Key Not Found!${NC}"
    echo -e "${YELLOW}Please upload your Firebase service account JSON key to:${NC}"
    echo -e "  ${PURPLE}${DEPLOY_DIR}/deploy/service-account.json${NC}"
    echo -e "${YELLOW}Then start the service with:${NC}"
    echo -e "  ${CYAN}sudo systemctl restart notifs-api.service${NC}"
    echo -e "${YELLOW}================================================================${NC}"
fi

echo -e "${GREEN}"
cat << "EOF"
==========================================================
    ✓ Provisioning Complete!
==========================================================
EOF
echo -e "${NC}"
echo -e "Next steps to configure your custom domain & SSL:"
echo -e "  1. Point your domain's DNS (A Record) to this VM's Public IP."
echo -e "  2. Obtain SSL Certificate with Certbot:"
echo -e "     ${CYAN}sudo certbot --nginx -d notifs.yourdomain.com${NC}"
echo -e "  3. Deploy full production Nginx config:"
echo -e "     ${CYAN}sudo cp ${DEPLOY_DIR}/deploy/nginx.conf /etc/nginx/sites-available/notifs.conf${NC}"
echo -e "     ${CYAN}sudo systemctl reload nginx${NC}"
echo -e "  4. Check backend status:"
echo -e "     ${CYAN}curl http://localhost:8000/health${NC}"
echo -e "     ${CYAN}sudo journalctl -u notifs-api.service -f${NC}"
echo ""
