#!/usr/bin/env bash
# install-lxc.sh — Install ixl CLI on OpenClaw LXC
#
#   scp install-lxc.sh root@192.168.1.14:/tmp/
#   ssh root@192.168.1.14 bash /tmp/install-lxc.sh
#
#   ssh root@192.168.1.14 'bash -s' < install-lxc.sh

set -euo pipefail

log() { echo "[$(date '+%H:%M:%S')] $*"; }

# ---------------------------------------------------------------
# 1. System deps for headless Chromium (skip if already present)
# ---------------------------------------------------------------
log "Checking system dependencies..."
MISSING_PKGS=()
for pkg in libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
           libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
           libpango-1.0-0 libcairo2 libxshmfence1 fonts-liberation; do
    dpkg -s "$pkg" &>/dev/null || MISSING_PKGS+=("$pkg")
done
# libasound2 was renamed to libasound2t64 in Debian 12+/Ubuntu 24+
if dpkg -s libasound2t64 &>/dev/null || dpkg -s libasound2 &>/dev/null; then
    :
else
    if apt-cache show libasound2t64 &>/dev/null 2>&1; then
        MISSING_PKGS+=(libasound2t64)
    else
        MISSING_PKGS+=(libasound2)
    fi
fi

if [[ ${#MISSING_PKGS[@]} -gt 0 ]]; then
    log "Installing missing packages: ${MISSING_PKGS[*]}"
    apt-get update -qq
    apt-get install -y -qq "${MISSING_PKGS[@]}"
else
    log "All system deps already installed"
fi

# ---------------------------------------------------------------
# 2. Install ixl CLI from GitHub
# ---------------------------------------------------------------
if command -v ixl &>/dev/null; then
    log "ixl CLI already installed: $(which ixl)"
    log "Upgrading..."
    pip install --upgrade git+https://github.com/bearyjd/ixl --break-system-packages -q
else
    log "Installing ixl CLI..."
    pip install git+https://github.com/bearyjd/ixl --break-system-packages -q
fi

# Browser dep (requests is in base, playwright is optional)
pip install 'ixl[browser]' --break-system-packages -q 2>/dev/null || true

# ---------------------------------------------------------------
# 3. Playwright / Chromium — only install if missing
# ---------------------------------------------------------------
if python3 -c "import playwright" &>/dev/null; then
    log "Playwright already installed"
    # Check if chromium browser binary exists
    CHROMIUM_PATH=$(python3 -c "from playwright._impl._driver import compute_driver_executable; import os; print(os.path.dirname(compute_driver_executable()))" 2>/dev/null || echo "")
    if [[ -n "$CHROMIUM_PATH" ]] && find "$CHROMIUM_PATH" -name "chromium*" -type f 2>/dev/null | head -1 | grep -q .; then
        log "Chromium browser already installed"
    else
        log "Installing Chromium browser..."
        playwright install chromium
    fi
else
    log "Installing Playwright + Chromium..."
    pip install playwright --break-system-packages -q
    playwright install chromium
fi

# ---------------------------------------------------------------
# 4. Clone repo for cron script (pip doesn't include it)
# ---------------------------------------------------------------
if [[ -d /opt/ixl/.git ]]; then
    log "Repo already at /opt/ixl — pulling latest"
    git -C /opt/ixl pull --ff-only -q
else
    log "Cloning repo to /opt/ixl..."
    git clone -q https://github.com/bearyjd/ixl.git /opt/ixl
fi
chmod +x /opt/ixl/cron/ixl-cron.sh

# ---------------------------------------------------------------
# 5. Configure accounts (skip if already exists)
# ---------------------------------------------------------------
mkdir -p ~/.ixl && chmod 700 ~/.ixl

if [[ -f ~/.ixl/accounts.env ]]; then
    log "accounts.env already exists — not overwriting"
else
    log "Creating accounts.env..."
    cat > ~/.ixl/accounts.env << 'EOF'
ford:fbeary@stmarkscs:lions2025!
jack:jbeary@stmarkscs:lions2025!
penn:pbeary@stmarkscs:lions2025!
EOF
    chmod 600 ~/.ixl/accounts.env
fi

if [[ -f ~/.ixl/.env ]]; then
    log ".env already exists — not overwriting"
else
    log "Creating default .env (Ford)..."
    cat > ~/.ixl/.env << 'EOF'
IXL_EMAIL="fbeary@stmarkscs"
IXL_PASSWORD="lions2025!"
EOF
    chmod 600 ~/.ixl/.env
fi

# ---------------------------------------------------------------
# 6. Smoke test
# ---------------------------------------------------------------
log "Running smoke test: ixl assigned --json (Ford)..."
if ixl assigned --json > /dev/null 2>&1; then
    log "Smoke test PASSED"
else
    log "WARN: Smoke test failed — may need /dev/shm or apparmor fix for Chromium in LXC"
    log "  Try: mount -t tmpfs -o size=256m tmpfs /dev/shm"
fi

log "Testing multi-account cron script..."
if /opt/ixl/cron/ixl-cron.sh 2>/dev/null; then
    log "Cron script PASSED — files in /tmp/ixl/:"
    ls -la /tmp/ixl/ 2>/dev/null || true
else
    log "WARN: Cron script had errors — check individual accounts"
fi

# ---------------------------------------------------------------
# Done
# ---------------------------------------------------------------
log ""
log "Installation complete!"
log ""
log "  ixl CLI:      $(which ixl)"
log "  Cron script:  /opt/ixl/cron/ixl-cron.sh"
log "  Accounts:     ~/.ixl/accounts.env"
log "  JSON output:  /tmp/ixl/"
log ""
log "Next steps:"
log "  1. Copy openclaw-agent.yaml into your OpenClaw agents.yaml"
log "  2. Create schedule in OpenClaw app:"
log "     Name: IXL Daily Report"
log "     Cron: 0 6 * * *"
log "     Prompt: Run the daily IXL report for all kids and send it to me via Signal."
