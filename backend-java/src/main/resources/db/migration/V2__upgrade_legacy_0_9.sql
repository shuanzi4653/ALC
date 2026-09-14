-- ============================================================
-- V2 旧库升级：为 0.8 及更早版本的既有数据库补齐 0.9 新增列
-- 说明：
--   1. 全部使用 ADD COLUMN IF NOT EXISTS，可重复执行（幂等）。
--   2. 新增的 NOT NULL 列一律带 DEFAULT，避免旧数据行无法满足非空约束
--      （这正是旧版 ddl-auto=update 直接失败的原因）。
--   3. 新库执行本脚本时所有列已存在，全部跳过，无副作用。
--   4. 旧记录缺失的字段保持 NULL 或默认值，不伪造观测值；业务层按
--      「未知」处理（见 Dashboard/前端 dataStatus 与质量标记）。
-- ============================================================

-- ---------- sfi_record：运行归属与完整观测快照 ----------
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS run_id VARCHAR(255);
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS region_id VARCHAR(255);
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS configured_mode VARCHAR(255);
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS effective_source VARCHAR(255);
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS degraded BOOLEAN DEFAULT FALSE NOT NULL;
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS degrade_reason VARCHAR(255);
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS obs_time VARCHAR(255);
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS ingested_at TIMESTAMP;
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS evaluated_at TIMESTAMP;
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS raw_sfi INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS hard_ban BOOLEAN DEFAULT FALSE NOT NULL;
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS rule_version VARCHAR(255);
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS condition_text VARCHAR(255);
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS wind_deg INTEGER;
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS pressure_hpa DOUBLE DEFAULT 0 NOT NULL;
ALTER TABLE sfi_record ADD COLUMN IF NOT EXISTS cloud_cover DOUBLE DEFAULT 0 NOT NULL;

-- 旧数据回填：raw_sfi 至少等于 sfi，避免历史行出现 0 分假象
UPDATE sfi_record SET raw_sfi = sfi WHERE raw_sfi = 0 AND sfi <> 0;
-- 旧数据回填：无 rule_version 的历史行标记为 legacy，便于与当前规则区分
UPDATE sfi_record SET rule_version = 'legacy' WHERE rule_version IS NULL;

-- ---------- track_result：运行归属与 revision ----------
ALTER TABLE track_result ADD COLUMN IF NOT EXISTS run_id VARCHAR(255);
ALTER TABLE track_result ADD COLUMN IF NOT EXISTS revision INTEGER DEFAULT 0 NOT NULL;
ALTER TABLE track_result ADD COLUMN IF NOT EXISTS status VARCHAR(255);

-- ---------- alert：提示去重与状态机字段 ----------
ALTER TABLE alert ADD COLUMN IF NOT EXISTS run_id VARCHAR(255);
ALTER TABLE alert ADD COLUMN IF NOT EXISTS episode_id VARCHAR(255);
ALTER TABLE alert ADD COLUMN IF NOT EXISTS status VARCHAR(255);
ALTER TABLE alert ADD COLUMN IF NOT EXISTS trigger_type VARCHAR(255);
ALTER TABLE alert ADD COLUMN IF NOT EXISTS transition_version INTEGER DEFAULT 0 NOT NULL;

-- 旧预警记录标记为已投递的历史事件，避免重复进入状态机
UPDATE alert SET status = 'FIRED' WHERE status IS NULL;

-- ---------- push_log：渠道业务响应字段 ----------
ALTER TABLE push_log ADD COLUMN IF NOT EXISTS alert_id BIGINT;
ALTER TABLE push_log ADD COLUMN IF NOT EXISTS latency_ms INTEGER DEFAULT 0 NOT NULL;

-- ---------- 索引（旧库补齐） ----------
CREATE INDEX IF NOT EXISTS idx_sfi_record_ts ON sfi_record (ts);
CREATE INDEX IF NOT EXISTS idx_sfi_record_region_source_rule ON sfi_record (region_id, effective_source, rule_version, ts);
CREATE INDEX IF NOT EXISTS idx_sfi_record_run_id ON sfi_record (run_id);
CREATE INDEX IF NOT EXISTS idx_alert_ts ON alert (ts);
CREATE INDEX IF NOT EXISTS idx_push_log_ts ON push_log (ts);
