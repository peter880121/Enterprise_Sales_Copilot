#!/bin/sh
set -eu
# Deliberately no shell tracing. Root credentials only exist in this one-shot container.
mc alias set core http://business-minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" >/dev/null
for bucket in esc-evidence esc-knowledge esc-parsed esc-export; do
  mc mb --ignore-existing "core/$bucket" >/dev/null
done
# Updates the same managed app identity on rerun; never touches other users/policies.
mc admin user add core "$MINIO_ACCESS_KEY" "$MINIO_SECRET_KEY" >/dev/null
mc admin policy create core esc-business /policies/business.json >/dev/null
mc admin policy attach core esc-business --user "$MINIO_ACCESS_KEY" >/dev/null
echo 'Business buckets and scoped policy initialized.'
