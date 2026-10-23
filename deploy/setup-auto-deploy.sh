#!/usr/bin/env bash
# One-time VM setup for the GitHub "Deploy" workflow (docs/deployment.md).
#
# Run as root from a checkout of this repository on the server:
#   sudo ./deploy/setup-auto-deploy.sh <ci-public-key-file> <host name CI connects to>
#
# Creates the `hmd-deploy` user whose SSH key can do exactly one thing: run
# /usr/local/bin/hmd-deploy <version>. The key gets no shell, no port/agent/X11 forwarding and
# no pty, and sudo allows that single script. Re-running is safe (it replaces the key).
set -euo pipefail

DEPLOY_USER=hmd-deploy
DEPLOY_DIR=/opt/notifs/deploy

die() { echo "ERROR: $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "run with sudo"
[ $# -eq 2 ] || die "usage: sudo $0 <ci-public-key-file> <host name, e.g. hmd-api.duckdns.org>"
pubkey_file=$1
host=$2
key=$(head -n 1 "$pubkey_file")
[[ "$key" =~ ^ssh-(ed25519|rsa)\ [A-Za-z0-9+/=]+ ]] || die "$pubkey_file is not an SSH public key"
[ -d "$DEPLOY_DIR" ] || die "$DEPLOY_DIR not found; run deploy/oracle-setup.sh first"

here=$(cd "$(dirname "$0")" && pwd)

# 1. User (needs a real shell: sshd runs the forced command through it)
if ! id -u "$DEPLOY_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$DEPLOY_USER"
  passwd --lock "$DEPLOY_USER" >/dev/null
fi

# 2. The only command the key may run
install -m 0755 -o root -g root "$here/hmd-deploy.sh" /usr/local/bin/hmd-deploy

# 3. sudo for exactly that file
sudoers=/etc/sudoers.d/hmd-deploy
echo "$DEPLOY_USER ALL=(root) NOPASSWD: /usr/local/bin/hmd-deploy" > "$sudoers.tmp"
chmod 0440 "$sudoers.tmp"
visudo -cf "$sudoers.tmp" >/dev/null || { rm -f "$sudoers.tmp"; die "sudoers check failed"; }
mv "$sudoers.tmp" "$sudoers"

# 4. The CI key, pinned to the deploy command ("restrict" = no forwarding, no pty)
ssh_dir="/home/$DEPLOY_USER/.ssh"
install -d -m 0700 -o "$DEPLOY_USER" -g "$DEPLOY_USER" "$ssh_dir"
echo "command=\"/usr/local/bin/hmd-deploy\",restrict $key" > "$ssh_dir/authorized_keys"
chown "$DEPLOY_USER:$DEPLOY_USER" "$ssh_dir/authorized_keys"
chmod 0600 "$ssh_dir/authorized_keys"

# 5. Compose file that knows about the published image (older installs built from source)
install -m 0644 "$here/docker-compose.yml" "$DEPLOY_DIR/docker-compose.yml"

echo
echo "Done. The deploy key can only run: hmd-deploy <version>"
echo
echo "Set this as the DEPLOY_KNOWN_HOSTS repository variable on GitHub:"
echo "------------------------------------------------------------------"
for f in /etc/ssh/ssh_host_*_key.pub; do
  echo "$host $(cut -d' ' -f1,2 "$f")"
done
echo "------------------------------------------------------------------"
echo "Test it from your PC:  ssh -i <private key> $DEPLOY_USER@$host 0.0.0   (should be refused: no such image)"
