#!/bin/bash
# ============================================================
# AI Grant Discovery System — VPS Deployment Script
# Server: 2.134.15.37 (Ubuntu)
# Run on VPS as root: bash deploy.sh
# ============================================================

set -e  # Exit on any error

echo "============================================"
echo " AI Grant Discovery System — VPS Deploy"
echo "============================================"

# ── 1. Update system ─────────────────────────────────────────
echo "[1/8] Updating system packages..."
apt-get update -q
apt-get upgrade -y -q

# ── 2. Install Docker ─────────────────────────────────────────
echo "[2/8] Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    echo "Docker installed successfully"
else
    echo "Docker already installed: $(docker --version)"
fi

# ── 3. Install Docker Compose ────────────────────────────────
echo "[3/8] Installing Docker Compose..."
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
    apt-get install -y docker-compose-plugin
fi
echo "Docker Compose: $(docker compose version)"

# ── 4. Clone / pull latest code ──────────────────────────────
echo "[4/8] Setting up project directory..."
PROJECT_DIR="/opt/ansar-grants"

if [ -d "$PROJECT_DIR" ]; then
    echo "Project exists, pulling latest..."
    cd "$PROJECT_DIR"
    git pull origin main || echo "Git pull failed — continuing with existing code"
else
    echo "Cloning project... (update with your repo URL if using git)"
    mkdir -p "$PROJECT_DIR"
    # If you have a git repo:
    # git clone https://github.com/your-org/ansar-grants.git "$PROJECT_DIR"
    # Otherwise copy files manually or use rsync from local:
    # rsync -av --exclude '.git' --exclude '.venv' . root@2.134.15.37:"$PROJECT_DIR"/
    echo "IMPORTANT: Copy project files to $PROJECT_DIR"
fi

cd "$PROJECT_DIR"

# ── 5. Verify .env file ──────────────────────────────────────
echo "[5/8] Checking .env..."
if [ ! -f ".env" ]; then
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "WARNING: .env created from example. Please edit it with your real values!"
        echo "Edit: nano $PROJECT_DIR/.env"
    else
        echo "ERROR: No .env file found!"
        exit 1
    fi
else
    echo ".env found"
fi

# ── 6. Configure firewall ─────────────────────────────────────
echo "[6/8] Configuring firewall..."
if command -v ufw &> /dev/null; then
    ufw allow 22/tcp    # SSH
    ufw allow 80/tcp    # HTTP (nginx → API)
    ufw allow 5678/tcp  # n8n editor
    ufw --force enable
    echo "Firewall configured"
fi

# ── 7. Build and start containers ────────────────────────────
echo "[7/8] Building and starting Docker containers..."
docker compose pull n8n nginx redis  # Pull pre-built images
docker compose build --no-cache backend bot  # Build custom images
docker compose up -d

echo "Waiting for services to start..."
sleep 15

# ── 8. Health check ──────────────────────────────────────────
echo "[8/8] Running health checks..."

# Check containers
echo "Container status:"
docker compose ps

# Check API
echo ""
echo "API health check..."
if curl -s -f http://localhost/health > /dev/null 2>&1; then
    echo "✓ API is healthy: http://2.134.15.37/api/"
else
    echo "⚠ API health check failed. Check logs: docker compose logs backend"
fi

# Check n8n
echo ""
echo "n8n check..."
if curl -s -f http://localhost:5678 > /dev/null 2>&1; then
    echo "✓ n8n is accessible: http://2.134.15.37:5678"
else
    echo "⚠ n8n not ready yet. May need more time to initialize."
fi

echo ""
echo "============================================"
echo " DEPLOYMENT COMPLETE"
echo "============================================"
echo ""
echo "Services:"
echo "  API:        http://2.134.15.37/api/"
echo "  Swagger:    http://2.134.15.37/docs"
echo "  n8n editor: http://2.134.15.37:5678"
echo ""
echo "Next steps:"
echo "  1. Set TELEGRAM_ALLOWED_USERS in .env (your Telegram ID)"
echo "  2. Set TELEGRAM_CHAT_ID in .env"
echo "  3. Import n8n workflows: n8n/workflows/*.json"
echo "  4. Set Vercel NEXT_PUBLIC_API_URL=http://2.134.15.37/api"
echo "  5. Message the bot on Telegram to verify it works"
echo ""
echo "Useful commands:"
echo "  View logs:     docker compose logs -f"
echo "  Restart:       docker compose restart"
echo "  Stop:          docker compose down"
echo "  Update:        git pull && docker compose up -d --build"
echo ""
