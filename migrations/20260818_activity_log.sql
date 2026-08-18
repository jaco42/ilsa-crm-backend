-- Migration: activity log
-- Date: 2026-08-18

BEGIN;

CREATE TABLE IF NOT EXISTS activity_log (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_nome    VARCHAR NOT NULL,
    action       VARCHAR NOT NULL,
    entity_type  VARCHAR NOT NULL,
    entity_id    VARCHAR,
    company_id   VARCHAR,
    company_nome VARCHAR,
    detail       JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_activity_log_created_at  ON activity_log (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_activity_log_user_nome   ON activity_log (user_nome);
CREATE INDEX IF NOT EXISTS ix_activity_log_company_id  ON activity_log (company_id);

COMMIT;
