#!/usr/bin/env bash
# ============================================================
# Ansar VPS first-boot provisioning / hardening
# Target: Ubuntu 24.04 LTS @ 31.210.174.74 (4 vCPU / 4 GB / 80 GB)
#
# RUN BY THE OWNER ON THE VPS as root (or via sudo), once:
#   bash provision.sh
#
# Idempotent: safe to re-run. It does NOT deploy the app — it prepares the host
# (deploy user, Docker, swap, ufw, fail2ban, /opt/ansar/* layout, shared net).
#
# BEFORE running: have your workstation SSH PUBLIC key ready (you will paste it,
# or set DEPLOY_PUBKEY below / export it). Root password login is disabled at
# the end but remains inactive until you manually restart ssh — make sure key
# login works first (the script reminds you).
# ============================================================
set -euo pipefail

DEPLOY_USER="${DEPLOY_USER:-deploy}"
DEPLOY_PUBKEY="${DEPLOY_PUBKEY:-}"     # paste an ssh-ed25519/ssh-rsa key, or leave empty to add manually
SWAP_SIZE="${SWAP_SIZE:-3G}"            # 2-4G recommended on a 4 GB box
ANSAR_ROOT="/opt/ansar"

log() { echo -e "\n=== $* ==="; }

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: run as root (sudo bash provision.sh)"; exit 1
fi

normalize_swap_size() {
  local raw="$1"
  if [[ ! "${raw}" =~ ^([1-9][0-9]*)([GgMm])$ ]]; then
    echo "ERROR: SWAP_SIZE must be an integer size ending in G/g or M/m, for example 3G or 3072M." >&2
    exit 1
  fi

  local amount="${BASH_REMATCH[1]}"
  local unit="${BASH_REMATCH[2]^^}"
  SWAP_SIZE="${amount}${unit}"
  if [[ "${unit}" == "G" ]]; then
    SWAP_SIZE_MB=$(( amount * 1024 ))
  else
    SWAP_SIZE_MB="${amount}"
  fi
}

normalize_swap_size "${SWAP_SIZE}"

# ── 1. Base packages ────────────────────────────────────────
log "[1/9] apt update + base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q ca-certificates curl gnupg ufw fail2ban git

# ── 2. deploy user (non-root, docker group, sudo) ───────────
log "[2/9] create non-root '${DEPLOY_USER}' user"
if ! id -u "${DEPLOY_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${DEPLOY_USER}"
fi
usermod -aG sudo "${DEPLOY_USER}"

# SSH key for deploy user
install -d -m 700 -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" "/home/${DEPLOY_USER}/.ssh"
AUTHKEYS="/home/${DEPLOY_USER}/.ssh/authorized_keys"
if [[ -n "${DEPLOY_PUBKEY}" ]]; then
  if ! grep -qF "${DEPLOY_PUBKEY}" "${AUTHKEYS}" 2>/dev/null; then
    echo "${DEPLOY_PUBKEY}" >> "${AUTHKEYS}"
  fi
fi
touch "${AUTHKEYS}"
chmod 600 "${AUTHKEYS}"
chown "${DEPLOY_USER}:${DEPLOY_USER}" "${AUTHKEYS}"
if [[ ! -s "${AUTHKEYS}" ]]; then
  echo "!! WARNING: ${AUTHKEYS} is EMPTY. Add your public key before logging out of root:"
  echo "   echo 'ssh-ed25519 AAAA... you@host' >> ${AUTHKEYS}"
fi

# ── 3. Swap (OOM insurance on 4 GB RAM) ─────────────────────
log "[3/9] swap ${SWAP_SIZE}"
if ! swapon --show | grep -q '/swapfile'; then
  fallocate -l "${SWAP_SIZE}" /swapfile || dd if=/dev/zero of=/swapfile bs=1M count="${SWAP_SIZE_MB}"
  chmod 600 /swapfile
  mkswap /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  sysctl -w vm.swappiness=10
  grep -q '^vm.swappiness' /etc/sysctl.conf || echo 'vm.swappiness=10' >> /etc/sysctl.conf
fi

# ── 4. Docker engine + compose plugin ───────────────────────
log "[4/9] Docker + compose plugin"
if ! command -v docker >/dev/null 2>&1; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${VERSION_CODENAME}") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
fi
usermod -aG docker "${DEPLOY_USER}"
docker --version
docker compose version

# ── 5. Shared Docker network ────────────────────────────────
log "[5/9] shared docker network 'ansar_shared'"
docker network inspect ansar_shared >/dev/null 2>&1 || docker network create ansar_shared

# ── 6. /opt/ansar layout ────────────────────────────────────
log "[6/9] /opt/ansar layout"
install -d -o "${DEPLOY_USER}" -g "${DEPLOY_USER}" \
  "${ANSAR_ROOT}" "${ANSAR_ROOT}/shared" "${ANSAR_ROOT}/grants" "${ANSAR_ROOT}/backups"
echo "Place shared compose/Caddyfile/.env in ${ANSAR_ROOT}/shared and clone the"
echo "grants repo into ${ANSAR_ROOT}/grants (the workflow expects it there)."

# ── 7. ufw — allow ONLY 22/80/443 ───────────────────────────
log "[7/9] ufw firewall (22/80/443 only)"
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose
# NOTE: Docker can bypass ufw by writing iptables directly. The compose files
# here publish NO ports for db/redis/n8n, so they are not exposed regardless.
# Only Caddy publishes 80/443 — which ufw allows. Do NOT add `ports:` host
# mappings for data services.

# ── 8. fail2ban (ssh) ───────────────────────────────────────
log "[8/9] fail2ban"
cat > /etc/fail2ban/jail.local <<'EOF'
[sshd]
enabled = true
port    = 22
maxretry = 5
findtime = 10m
bantime  = 1h
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban

# ── 9. SSH hardening (key-only, no root login) ──────────────
log "[9/9] SSH hardening"
SSHD_DROPIN="/etc/ssh/sshd_config.d/99-ansar-hardening.conf"
cat > "${SSHD_DROPIN}" <<'EOF'
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
ChallengeResponseAuthentication no
EOF
if ! sshd -t; then
  echo "ERROR: staged SSH hardening drop-in is invalid: ${SSHD_DROPIN}" >&2
  echo "SSH hardening was NOT applied. Fix the drop-in and re-run sshd -t before restarting ssh." >&2
  exit 1
fi
echo "!! Verify key login as '${DEPLOY_USER}' in a SEPARATE terminal BEFORE"
echo "!! closing this session. Key-only SSH hardening is staged and syntax-valid,"
echo "!! but it is INACTIVE until you manually run:"
echo "!!   systemctl restart ssh"
echo "!! (Not auto-restarted to avoid locking you out.)"

log "DONE: host prepared; SSH hardening staged but INACTIVE"
cat <<EOF

Next (owner):
  1. Confirm 'ssh ${DEPLOY_USER}@31.210.174.74' works with your key.
  2. systemctl restart ssh   (this is when key-only SSH/root-password lockout takes effect)
  3. Copy shared compose/Caddyfile/.env -> ${ANSAR_ROOT}/shared/
  4. Clone repo -> ${ANSAR_ROOT}/grants/ and add deploy/grants/.env
  5. Bring up shared, then grants (see deploy/MIGRATION-RUNBOOK.md).
  6. Install the nightly backup cron (see deploy/backup.sh).
EOF
