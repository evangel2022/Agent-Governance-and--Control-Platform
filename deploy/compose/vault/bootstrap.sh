#!/usr/bin/env sh
# Idempotent Vault bootstrap for the development stack.
#
# Enables the KV v2 secrets engine and creates the Transit key used for
# application-level encryption of sensitive columns. Safe to run repeatedly.
#
# WARNING: development only. The dev server uses an in-memory store and a
# well-known root token. Do not use this script against a real Vault.
set -eu

VAULT_ADDR="${VAULT_ADDR:-http://localhost:8200}"
VAULT_TOKEN="${VAULT_TOKEN:-root}"
KV_MOUNT="${KV_MOUNT:-secret}"
TRANSIT_MOUNT="${TRANSIT_MOUNT:-transit}"
TRANSIT_KEY="${TRANSIT_KEY:-gov-sensitive}"

export VAULT_ADDR VAULT_TOKEN

until vault status >/dev/null 2>&1; do
  echo "waiting for vault at ${VAULT_ADDR}..."
  sleep 2
done

if vault secrets list -format=json | grep -q "\"${KV_MOUNT}/\""; then
  echo "kv v2 already enabled at ${KV_MOUNT}/"
else
  vault secrets enable -path="${KV_MOUNT}" -version=2 kv
  echo "enabled kv v2 at ${KV_MOUNT}/"
fi

if vault secrets list -format=json | grep -q "\"${TRANSIT_MOUNT}/\""; then
  echo "transit already enabled at ${TRANSIT_MOUNT}/"
else
  vault secrets enable -path="${TRANSIT_MOUNT}" transit
  echo "enabled transit at ${TRANSIT_MOUNT}/"
fi

if vault read -format=json "${TRANSIT_MOUNT}/keys/${TRANSIT_KEY}" >/dev/null 2>&1; then
  echo "transit key ${TRANSIT_KEY} already exists"
else
  vault write -f "${TRANSIT_MOUNT}/keys/${TRANSIT_KEY}"
  echo "created transit key ${TRANSIT_KEY}"
fi

echo "vault bootstrap complete"
