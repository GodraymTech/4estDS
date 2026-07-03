-- 4estDS PostGIS 行级安全 (RLS) / 多租户隔离 (P2 ⑤)
-- ------------------------------------------------------------------
-- 在 schema.sql 之后执行。为六张业务表统一加 tenant_id 并启用 RLS,
-- 以会话级 GUC app.tenant_id 做租户隔离; 应用角色 forestds_app 受策略约束,
-- 迁移/运维以表属主或超级用户执行(可临时 SET app.tenant_id 或 BYPASSRLS)。
-- 幂等: 可安全重复执行。
--
-- 应用取得连接后、执行任何业务查询前绑定租户:
--   SELECT set_config('app.tenant_id', '<tenant>', false);
-- 未设置时 current_setting('app.tenant_id', true) 返回 NULL, 策略拒绝所有行(默认安全)。

CREATE EXTENSION IF NOT EXISTS postgis;

-- 应用角色(受 RLS 约束; 运维/迁移请用属主或超级用户)。
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'forestds_app') THEN
    CREATE ROLE forestds_app LOGIN PASSWORD 'change_me_forestds';
  END IF;
END $$;

GRANT USAGE ON SCHEMA public TO forestds_app;

-- 为六张业务表统一加 tenant_id + 启用/强制 RLS + 租户隔离策略 + 索引 + 授权(DRY 循环)。
DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'run_logs', 'tree_individuals', 'tracts',
    'tract_sources', 'tree_observations', 'tract_trees'
  ];
BEGIN
  FOREACH t IN ARRAY tables LOOP
    EXECUTE format(
      'ALTER TABLE %I ADD COLUMN IF NOT EXISTS tenant_id text NOT NULL DEFAULT ''default''', t);
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    -- FORCE: 表属主也受策略约束, 避免应用误用属主连接绕过隔离。
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I '
      'USING (tenant_id = current_setting(''app.tenant_id'', true)) '
      'WITH CHECK (tenant_id = current_setting(''app.tenant_id'', true))', t);
    EXECUTE format(
      'CREATE INDEX IF NOT EXISTS %I ON %I (tenant_id)', 'idx_' || t || '_tenant', t);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO forestds_app', t);
  END LOOP;
END $$;

-- 地块唯一性纳入租户维度(不同租户可有同名同时相地块)。
ALTER TABLE tracts DROP CONSTRAINT IF EXISTS tracts_acquisition_time_location_key;
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'tracts_tenant_acq_loc_key'
  ) THEN
    ALTER TABLE tracts ADD CONSTRAINT tracts_tenant_acq_loc_key
      UNIQUE (tenant_id, acquisition_time, location);
  END IF;
END $$;
