#!/usr/bin/env bash
# Deploys one published server image version, verifies it, and rolls back if it is unhealthy.
#
# Installed as /usr/local/bin/hmd-deploy by deploy/setup-auto-deploy.sh. Two ways in:
#   - As the forced command of the CI deploy key: the requested version arrives in
#     $SSH_ORIGINAL_COMMAND. It is validated here, then the script re-runs itself as root via
#     sudo (sudoers allows exactly this file, and sudo resets the environment).
#   - By hand, as root: `sudo hmd-deploy 0.2.0`. Deploying an older version is a rollback.
#
# Exit codes: 0 deployed and healthy; 1 refused or failed (the previous version keeps running).
set -euo pipefail

ENV_FILE="${HMD_ENV_FILE:-/opt/notifs/deploy/.env}"
COMPOSE_DIR="${HMD_COMPOSE_DIR:-/opt/notifs/deploy}"
SERVICE="${HMD_SERVICE:-notifs-api.service}"
HEALTH_URL="${HMD_HEALTH_URL:-http://127.0.0.1:8000/health}"
HEALTH_TIMEOUT="${HMD_HEALTH_TIMEOUT:-90}"
HEALTH_INTERVAL="${HMD_HEALTH_INTERVAL:-2}"
LOCK_FILE="${HMD_LOCK_FILE:-/run/lock/hmd-deploy.lock}"
SELF="${HMD_SELF:-/usr/local/bin/hmd-deploy}"
DEFAULT_REPO="ghcr.io/w0nb0n/hows-my-download-server"
# Release versions (0.2.0) or test builds (sha-1a2b3c4); nothing else reaches docker or sudo
VERSION_RE='^([0-9]+\.[0-9]+\.[0-9]+|sha-[0-9a-f]{7,40})$'

log() { echo "[hmd-deploy] $*"; }
die() { echo "[hmd-deploy] ERROR: $*" >&2; exit 1; }

# Forced-command entry: validate before anything is passed on
if [ $# -eq 0 ] && [ -n "${SSH_ORIGINAL_COMMAND:-}" ]; then
  requested="$SSH_ORIGINAL_COMMAND"
  [[ "$requested" =~ $VERSION_RE ]] || die "refusing invalid version '$requested'"
  exec sudo -n "$SELF" "$requested"
fi

[ $# -eq 1 ] || die "usage: hmd-deploy <version>   (e.g. 0.2.0, or sha-1a2b3c4)"
version="$1"
[[ "$version" =~ $VERSION_RE ]] || die "invalid version '$version'"
if [ "$(id -u)" -ne 0 ] && [ -z "${HMD_DEPLOY_ALLOW_NON_ROOT:-}" ]; then
  die "must run as root (sudo hmd-deploy $version)"
fi
[ -f "$ENV_FILE" ] || die "missing $ENV_FILE"

# One deploy at a time
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK_FILE"
  flock -n 9 || die "another deploy is already running"
fi

previous=$(grep -E '^HMD_IMAGE=' "$ENV_FILE" | tail -n 1 | cut -d= -f2- || true)
repo="$DEFAULT_REPO"
if [[ "$previous" == */*:* ]]; then
  repo="${previous%:*}"  # keep a self-hoster's own registry path
fi
target="$repo:$version"

set_image() {
  # Rewrites the file in place so its owner and permissions (it holds config) are kept
  local tmp
  tmp=$(mktemp)
  grep -v -E '^HMD_IMAGE=' "$ENV_FILE" > "$tmp" || true
  [ -n "$1" ] && echo "HMD_IMAGE=$1" >> "$tmp"
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}

healthy() {
  # $1: version /health must report, or empty to accept any healthy server
  local deadline=$((SECONDS + HEALTH_TIMEOUT)) body
  while [ "$SECONDS" -lt "$deadline" ]; do
    if body=$(curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null); then
      if [ -z "$1" ] || grep -q "\"version\":\"$1\"" <<<"$body"; then
        echo "$body"
        return 0
      fi
    fi
    sleep "$HEALTH_INTERVAL"
  done
  return 1
}

log "deploying $target (currently: ${previous:-compose default})"
(cd "$COMPOSE_DIR" && HMD_IMAGE="$target" docker compose pull notifs-api) \
  || die "could not pull $target; nothing changed"

set_image "$target"
systemctl restart "$SERVICE"

# Release images report their version on /health; test (sha-) builds report the next one
expected=""
[[ "$version" =~ ^[0-9] ]] && expected="$version"
if body=$(healthy "$expected"); then
  log "healthy: $body"
  log "deployed $target"
  exit 0
fi

log "$target did not become healthy within ${HEALTH_TIMEOUT}s; rolling back"
set_image "$previous"
systemctl restart "$SERVICE"
if healthy "" >/dev/null; then
  die "rolled back to ${previous:-compose default}; $target was NOT deployed"
fi
die "rollback is unhealthy too; check: journalctl -u $SERVICE -n 100"
