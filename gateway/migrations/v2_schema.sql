-- ========================================================
-- Kelivo Memory System v2.0 - 数据库迁移脚本
-- 执行方式：在 Supabase SQL Editor 中运行
-- 日期：2026-02-18
-- ========================================================

-- ========== 启用扩展 ==========
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ========== conversations 表新增字段 ==========
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS scene_type TEXT DEFAULT 'daily';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS topic TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS entities TEXT[] DEFAULT '{}';
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS emotion TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- conversations 索引
CREATE INDEX IF NOT EXISTS idx_conv_scene ON conversations(scene_type);
CREATE INDEX IF NOT EXISTS idx_conv_entities ON conversations USING GIN(entities);
CREATE INDEX IF NOT EXISTS idx_conv_trgm_user ON conversations USING GIN(user_msg gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_conv_trgm_asst ON conversations USING GIN(assistant_msg gin_trgm_ops);
-- 注意：ivfflat索引需要表中已有一定数据量才能创建，如果报错可以先跳过，等有数据后再建
-- CREATE INDEX IF NOT EXISTS idx_conv_embedding ON conversations USING ivfflat(embedding vector_cosine_ops) WITH (lists = 50);

-- ========== summaries 表新增字段 ==========
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS scene_type TEXT DEFAULT 'daily';
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS topic TEXT;
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS entities TEXT[] DEFAULT '{}';
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS emotion TEXT;
ALTER TABLE summaries ADD COLUMN IF NOT EXISTS embedding vector(1024);

-- summaries 索引
CREATE INDEX IF NOT EXISTS idx_sum_scene ON summaries(scene_type);
-- CREATE INDEX IF NOT EXISTS idx_sum_embedding ON summaries USING ivfflat(embedding vector_cosine_ops) WITH (lists = 20);

-- ========== 同义词映射表（新建） ==========
CREATE TABLE IF NOT EXISTS synonym_map (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    term TEXT NOT NULL,
    synonyms TEXT[] NOT NULL,
    category TEXT DEFAULT 'general',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 插入初始同义词数据
INSERT INTO synonym_map (term, synonyms, category) VALUES
('Krueger', ARRAY['Krueger', 'Sebastian', '克鲁格', 'K'], 'character'),
('Dream', ARRAY['Dream', '宝贝'], 'person'),
('剧本', ARRAY['剧本', '角色扮演', '剧情', '演', 'RP'], 'scene'),
('纹身', ARRAY['纹身', '双头鹰', '胸前'], 'detail'),
('KSK', ARRAY['KSK', 'Kommando Spezialkräfte', '特种部队'], 'org'),
('奇美拉', ARRAY['奇美拉', 'Chimera'], 'org'),
('伪装网', ARRAY['伪装网', '面罩', '脸'], 'detail'),
('雇佣兵', ARRAY['雇佣兵', '佣兵', 'mercenary'], 'role'),
('占有欲', ARRAY['占有欲', '吃醋', '嫉妒', '醋意'], 'emotion'),
('处决', ARRAY['处决', '绞杀', '杀'], 'action')
ON CONFLICT DO NOTHING;

-- ========== 验证 ==========
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name = 'conversations' AND column_name = 'scene_type';
-- 应返回1行

-- SELECT count(*) FROM synonym_map;
-- 应返回10
