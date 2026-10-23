#!/usr/bin/env bash
# Tests for deploy/hmd-deploy.sh with stub docker/systemctl/curl/sudo on PATH.
#
# The fake server "runs" whatever HMD_IMAGE the env file names when systemctl restarts it,
# and reports that tag as its version on /health, unless the tag is listed in FAIL_VERSIONS
# (that version never becomes healthy). Run: bash deploy/tests/test_hmd_deploy.sh
set -uo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SCRIPT="$ROOT/deploy/hmd-deploy.sh"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
passed=0
failed=0

cat > "$WORK/bin/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $* HMD_IMAGE=${HMD_IMAGE:-}" >> "$STATE/calls"
[[ "${HMD_IMAGE:-}" == *":${PULL_FAILS:-none}" ]] && exit 1
exit 0
EOF
cat > "$WORK/bin/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "systemctl $*" >> "$STATE/calls"
image=$(grep -E '^HMD_IMAGE=' "$HMD_ENV_FILE" | tail -n 1 | cut -d= -f2-)
tag="${image##*:}"
if [ -z "$image" ]; then tag="default"; fi
if [[ " ${FAIL_VERSIONS:-} " == *" $tag "* ]]; then : > "$STATE/health"
else printf '{"status":"ok","version":"%s","timestamp":"t"}' "$tag" > "$STATE/health"; fi
EOF
cat > "$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
[ -s "$STATE/health" ] || exit 22
cat "$STATE/health"
EOF
cat > "$WORK/bin/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo $*" >> "$STATE/calls"
EOF
chmod +x "$WORK/bin/"*

# Fresh state per test: env file at version $1 (empty = no HMD_IMAGE line)
setup() {
  export STATE="$WORK/state.$RANDOM"
  mkdir -p "$STATE"
  export HMD_ENV_FILE="$STATE/.env"
  printf 'STORE_TYPE=firestore\nNOTIFIER_TYPE=fcm\n' > "$HMD_ENV_FILE"
  [ -n "${1:-}" ] && echo "HMD_IMAGE=ghcr.io/me/hows-my-download-server:$1" >> "$HMD_ENV_FILE"
  : > "$STATE/calls"
  export PATH="$WORK/bin:$PATH" HMD_COMPOSE_DIR="$STATE" HMD_LOCK_FILE="$STATE/lock"
  export HMD_DEPLOY_ALLOW_NON_ROOT=1 HMD_HEALTH_TIMEOUT=1 HMD_HEALTH_INTERVAL=0.1
  export HMD_HEALTH_URL="http://test/health" HMD_SELF="/usr/local/bin/hmd-deploy"
  unset FAIL_VERSIONS PULL_FAILS SSH_ORIGINAL_COMMAND
}

image_in_env() { grep -E '^HMD_IMAGE=' "$HMD_ENV_FILE" | cut -d= -f2-; }
# The last run failed without calling docker, systemctl or sudo
refused() { [ "$code" -ne 0 ] && [ ! -s "$STATE/calls" ]; }

check() {
  # check <description> <condition...>
  local name=$1
  shift
  if "$@"; then passed=$((passed + 1)); echo "ok   - $name"
  else failed=$((failed + 1)); echo "FAIL - $name"; fi
}

# 1. Healthy deploy switches the image and keeps other settings
setup 0.2.0
out=$(bash "$SCRIPT" 0.3.0 2>&1); code=$?
check "healthy deploy exits 0" test "$code" -eq 0
check "env file points at the new image" test "$(image_in_env)" = "ghcr.io/me/hows-my-download-server:0.3.0"
check "other settings are kept" grep -q '^STORE_TYPE=firestore$' "$HMD_ENV_FILE"
check "keeps the registry path already in use" grep -q 'HMD_IMAGE=ghcr.io/me/hows-my-download-server:0.3.0' "$STATE/calls"
check "reports the healthy version" grep -q '"version":"0.3.0"' <<<"$out"

# 2. Unhealthy version is rolled back
setup 0.2.0
export FAIL_VERSIONS="0.3.1"
out=$(bash "$SCRIPT" 0.3.1 2>&1); code=$?
check "unhealthy deploy exits non-zero" test "$code" -ne 0
check "env file is restored" test "$(image_in_env)" = "ghcr.io/me/hows-my-download-server:0.2.0"
check "service restarted twice (deploy + rollback)" test "$(grep -c 'systemctl restart' "$STATE/calls")" -eq 2
check "says it rolled back" grep -q "rolled back to" <<<"$out"

# 3. Pull failure changes nothing
setup 0.2.0
export PULL_FAILS="0.4.0"
bash "$SCRIPT" 0.4.0 >/dev/null 2>&1; code=$?
check "pull failure exits non-zero" test "$code" -ne 0
check "pull failure leaves env file alone" test "$(image_in_env)" = "ghcr.io/me/hows-my-download-server:0.2.0"
check "pull failure does not restart" bash -c "! grep -q systemctl '$STATE/calls'"

# 4. Invalid versions never reach docker
# shellcheck disable=SC2016  # '$(id)' must stay literal: it is the injection attempt
for bad in "latest" "0.3" "0.3.0;reboot" '$(id)' "../0.3.0" "0.3.0 0.4.0"; do
  setup 0.2.0
  bash "$SCRIPT" "$bad" >/dev/null 2>&1; code=$?
  check "rejects '$bad'" refused
done

# 5. Forced-command path validates, then re-runs itself via sudo
setup 0.2.0
SSH_ORIGINAL_COMMAND="0.3.0" bash "$SCRIPT" >/dev/null 2>&1
check "forced command hands a valid version to sudo" grep -qx "sudo -n /usr/local/bin/hmd-deploy 0.3.0" "$STATE/calls"
setup 0.2.0
SSH_ORIGINAL_COMMAND="0.3.0; rm -rf /" bash "$SCRIPT" >/dev/null 2>&1; code=$?
check "forced command refuses an injected command" refused
setup 0.2.0
SSH_ORIGINAL_COMMAND="bash" bash "$SCRIPT" >/dev/null 2>&1; code=$?
check "forced command refuses a shell" refused

# 6. Test builds (sha-) only need a healthy server, not a matching version
setup 0.2.0
bash "$SCRIPT" sha-7927d81 >/dev/null 2>&1; code=$?
check "sha build deploys when healthy" test "$code" -eq 0

# 7. First deploy on an install without HMD_IMAGE uses the default registry path
setup ""
bash "$SCRIPT" 0.2.0 >/dev/null 2>&1; code=$?
check "first deploy succeeds" test "$code" -eq 0
check "first deploy uses the default image" test "$(image_in_env)" = "ghcr.io/w0nb0n/hows-my-download-server:0.2.0"

# 8. ...and a failed first deploy removes the line again
setup ""
export FAIL_VERSIONS="0.2.0"
bash "$SCRIPT" 0.2.0 >/dev/null 2>&1; code=$?
check "failed first deploy exits non-zero" test "$code" -ne 0
check "failed first deploy leaves no HMD_IMAGE" test -z "$(image_in_env)"

# 9. Refuses to run as a normal user outside the forced-command path
setup 0.2.0
if [ "$(id -u)" -ne 0 ]; then
  HMD_DEPLOY_ALLOW_NON_ROOT="" bash "$SCRIPT" 0.3.0 >/dev/null 2>&1; code=$?
  check "non-root direct run is refused" refused
fi

echo
echo "$passed passed, $failed failed"
[ "$failed" -eq 0 ]
