#!/bin/bash
# Runs once, as $POSTGRES_USER (the cluster's bootstrap superuser - see docker-compose.yml),
# against a fresh/empty data volume only. Creates the actual app role that the API and
# tests connect as (api/.env.example, Makefile's `test` target). Deliberately a distinct,
# ordinary (non-superuser) role: Postgres RLS and migration 0002's REVOKE are
# unconditionally bypassed for superusers regardless of table ownership, and Postgres
# refuses to ever strip SUPERUSER from the bootstrap user itself - so the app role must
# never be the bootstrap user, here or in CI (.github/workflows/ci.yml has the same split).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE ROLE redactproof WITH LOGIN PASSWORD 'redactproof';
    CREATE DATABASE redactproof OWNER redactproof;
    CREATE DATABASE redactproof_test OWNER redactproof;
EOSQL

for db in redactproof redactproof_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-EOSQL
      ALTER SCHEMA public OWNER TO redactproof;
EOSQL
done
