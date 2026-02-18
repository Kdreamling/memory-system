-- ========================================================
-- Kelivo Memory System v2.0 - 回滚脚本
-- 如果需要回滚阶段1的数据库变更
-- ========================================================

ALTER TABLE conversations DROP COLUMN IF EXISTS scene_type;
ALTER TABLE conversations DROP COLUMN IF EXISTS topic;
ALTER TABLE conversations DROP COLUMN IF EXISTS entities;
ALTER TABLE conversations DROP COLUMN IF EXISTS emotion;
ALTER TABLE conversations DROP COLUMN IF EXISTS embedding;

ALTER TABLE summaries DROP COLUMN IF EXISTS scene_type;
ALTER TABLE summaries DROP COLUMN IF EXISTS topic;
ALTER TABLE summaries DROP COLUMN IF EXISTS entities;
ALTER TABLE summaries DROP COLUMN IF EXISTS emotion;
ALTER TABLE summaries DROP COLUMN IF EXISTS embedding;

DROP TABLE IF EXISTS synonym_map;

-- 删除相关索引（DROP COLUMN会自动删除依赖的索引，但以防万一）
DROP INDEX IF EXISTS idx_conv_scene;
DROP INDEX IF EXISTS idx_conv_entities;
DROP INDEX IF EXISTS idx_conv_trgm_user;
DROP INDEX IF EXISTS idx_conv_trgm_asst;
DROP INDEX IF EXISTS idx_conv_embedding;
DROP INDEX IF EXISTS idx_sum_scene;
DROP INDEX IF EXISTS idx_sum_embedding;
