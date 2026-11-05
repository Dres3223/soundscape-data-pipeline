#!/usr/bin/env bash
# Creates .env from .env.example, replacing every placeholder secret
# (values starting with "change-me") with a random one.
# Never overwrites an existing .env, so your current secrets are safe.
#
# Usage (from the project root):
#   bash scripts/make_env.sh

set -euo pipefail

EXAMPLE=".env.example"
TARGET=".env"

if [ -f "$TARGET" ]; then
  echo ">> $TARGET already exists: left as it is"
  exit 0
fi

random_secret() { openssl rand -hex 24; }
# Airflow's Fernet key: 32 random bytes in url-safe base64
fernet_key() { openssl rand -base64 32 | tr '+/' '-_'; }

# Created with owner-only permissions before any secret is written to it
umask 077
while IFS= read -r line || [ -n "$line" ]; do
  case "$line" in
    AIRFLOW_FERNET_KEY=*) echo "AIRFLOW_FERNET_KEY=$(fernet_key)" ;;
    *=change-me*) echo "${line%%=*}=$(random_secret)" ;;
    *) echo "$line" ;;
  esac
done < "$EXAMPLE" > "$TARGET"

echo ">> Created $TARGET with random secrets (permissions: $(stat -f %Lp "$TARGET" 2>/dev/null || stat -c %a "$TARGET"))"
