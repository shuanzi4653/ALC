-- ============================================================
-- V6 每日配额台账：把「一天之内最多烧多少」记在库里
-- ============================================================
--
-- 背景：2026-10-14 拆掉登录门，服务端不再认识"谁"。nginx 的 limit_req 只约束
--       频率（20 r/m/源 IP），约束不了总量 —— 慢速持续调用照样能在一天里把
--       DeepSeek 额度烧完。这张表就是总量那一格。
--
-- 为什么落库而不是放内存：
--   配额的语义是"一天内总量有上限"。放内存里，一次重启就把它清零了 ——
--   等于留了一条「重启即重置」的旁路。落库之后重启不影响配额。
--   代价是每次计费多两行读写，相对于一次几秒的大模型调用可以忽略。
--
-- 行粒度 = (quota_day, dimension, key)。bucket_key 是这三者拼出来的单列主键，
--   让计费退化成「findById + UPDATE ... WHERE used < limit」两步，
--   条件与自增在同一次行锁里完成 —— 先读后写在并发下会让上限静默失效。
--
-- ⚠️ 列名是 quota_day，**不是 day**。H2 把 DAY 当保留字（INTERVAL 字面量的单位），
--    `day VARCHAR(10)` 直接报 `Syntax error ... expected "identifier"`。
--    这一条是 2026-10-14 用真实 H2 跑本脚本时才发现的 —— 而那之前，整条
--    Java 单测（用 Mockito 假仓库）对它**完全无话可说**：假仓库里没有 SQL。
--    所以不要为了"更好看"把它改回 day；也不要用双引号 `"day"` 绕过 ——
--    一旦带引号，H2 就按大小写敏感处理，而 Hibernate 生成的是不带引号的小写，
--    两边会指向不同的标识符。
--
-- 只增不改：这张表不参与工作区隔离（配额是"这台机器今天被用了多少"，
--   与"谁看哪份数据"是两件事），所以**没有 workspace 过滤**，也不需要
--   像 agent_chat 那样加归属列。
--
-- 幂等：IF NOT EXISTS；Flyway 另行记录版本，重复执行无副作用。
-- ============================================================

CREATE TABLE IF NOT EXISTS llm_quota (
    bucket_key VARCHAR(160) PRIMARY KEY,
    quota_day  VARCHAR(10)  NOT NULL,
    dimension  VARCHAR(12)  NOT NULL,
    quota_key  VARCHAR(64)  NOT NULL,
    used       INTEGER      NOT NULL DEFAULT 0,
    created_at TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 按日清理与按日统计都只用到 quota_day 这一列。
CREATE INDEX IF NOT EXISTS idx_llm_quota_day ON llm_quota (quota_day);
