#!/usr/bin/env bash
# AragonTeam 首次部署的系统依赖、运行账号与环境配置。

set -euo pipefail

readonly PROJECT_DIR="/opt/aragonteam"
readonly RUN_USER="aragonteam"
readonly RUN_GROUP="aragonteam"
readonly DATA_DIR="/var/lib/aragonteam"
readonly ENV_DIR="/etc/aragonteam"
readonly ENV_FILE="${ENV_DIR}/aragonteam.env"
readonly PUBLIC_ORIGIN="http://120.26.57.40"

if [[ "$(id -u)" -ne 0 ]]; then
  echo "ERROR: provision.sh must run as root." >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl nginx nodejs npm openssl \
  python3-pip python3-venv

if ! id "$RUN_USER" >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$DATA_DIR" \
    --shell /usr/sbin/nologin "$RUN_USER"
fi

install -d -m 0750 -o "$RUN_USER" -g "$RUN_GROUP" "$PROJECT_DIR"
install -d -m 0750 -o "$RUN_USER" -g "$RUN_GROUP" \
  "$DATA_DIR" "$DATA_DIR/uploads" "$PROJECT_DIR/logs"
install -d -m 0750 -o root -g "$RUN_GROUP" "$ENV_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  secret_key="$(openssl rand -hex 32)"
  jwt_secret_key="$(openssl rand -hex 32)"
  umask 0027
  {
    printf 'SECRET_KEY=%s\n' "$secret_key"
    printf 'JWT_SECRET_KEY=%s\n' "$jwt_secret_key"
    printf 'DATABASE_URL=sqlite:////var/lib/aragonteam/aragon.db\n'
    printf 'CORS_ORIGINS=%s\n' "$PUBLIC_ORIGIN"
    printf 'SEED_ON_STARTUP=true\n'
    printf 'RELEASE_STALE_LOCKS_ON_STARTUP=true\n'
    printf 'UPLOAD_DIR=/var/lib/aragonteam/uploads\n'
    printf 'DOC_AGENT_ARCHIVE=false\n'
    printf 'SQLITE_SYNCHRONOUS=NORMAL\n'
  } > "$ENV_FILE"
fi
chown root:"$RUN_GROUP" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

printf 'NEXT_PUBLIC_API_BASE=%s/api\n' "$PUBLIC_ORIGIN" \
  > "$PROJECT_DIR/frontend/.env.production"
chown "$RUN_USER":"$RUN_GROUP" "$PROJECT_DIR/frontend/.env.production"
chmod 0644 "$PROJECT_DIR/frontend/.env.production"

chown -R "$RUN_USER":"$RUN_GROUP" "$PROJECT_DIR"
find "$PROJECT_DIR/ops" -maxdepth 1 -type f -name '*.sh' \
  -exec chmod 0755 {} +

node_major="$(node --version | sed 's/^v//' | cut -d. -f1)"
if [[ "$node_major" -lt 18 ]]; then
  echo "ERROR: Node.js 18+ is required; installed $(node --version)." >&2
  exit 1
fi

echo "Provisioning complete: Python $(python3 --version 2>&1), Node $(node --version), Nginx $(nginx -v 2>&1)"
