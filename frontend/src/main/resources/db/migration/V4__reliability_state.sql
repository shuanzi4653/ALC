-- 0.10 reliability state: run-aware alert recovery and recoverable outbox claims.
ALTER TABLE alert_state ADD COLUMN IF NOT EXISTS last_evaluated_run_sequence BIGINT;
ALTER TABLE outbox_event ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMP;
CREATE INDEX IF NOT EXISTS idx_outbox_claimed ON outbox_event (status, claimed_at);
