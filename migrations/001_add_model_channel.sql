-- ============================================================
-- Migration 001: 新增 model_channel 字段实现多 Bot 记忆隔离
-- 执行方式：在 Supabase SQL Editor 中逐段执行
-- 日期：2026-02-23
-- ============================================================

-- ============ 第一段：conversations 表加字段 ============
-- 新增 model_channel 列，默认值 'deepseek'
-- 所有历史数据自动归入 deepseek 通道
ALTER TABLE conversations
ADD COLUMN IF NOT EXISTS model_channel TEXT DEFAULT 'deepseek';

-- ============ 第二段：summaries 表加字段 ============
ALTER TABLE summaries
ADD COLUMN IF NOT EXISTS model_channel TEXT DEFAULT 'deepseek';

-- ============ 第三段：创建索引（加速按 channel 过滤） ============
CREATE INDEX IF NOT EXISTS idx_conv_channel ON conversations(model_channel);
CREATE INDEX IF NOT EXISTS idx_sum_channel ON summaries(model_channel);

-- 复合索引（channel + 时间，优化常见查询模式）
CREATE INDEX IF NOT EXISTS idx_conv_channel_created ON conversations(model_channel, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sum_channel_created ON summaries(model_channel, created_at DESC);

-- ============ 第四段：修改 RPC 函数 search_conversations_v2 ============
-- 新增 filter_channel 参数，默认 'deepseek'
-- 加入 model_channel 过滤条件
CREATE OR REPLACE FUNCTION search_conversations_v2(
    query_embedding vector(1024),
    match_count int DEFAULT 5,
    filter_scene text DEFAULT 'daily',
    filter_channel text DEFAULT 'deepseek'
)
RETURNS TABLE(
    id uuid,
    user_msg text,
    assistant_msg text,
    created_at timestamptz,
    scene_type text,
    topic text,
    emotion text,
    round_number int,
    similarity float
)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id, c.user_msg, c.assistant_msg, c.created_at,
        c.scene_type, c.topic, c.emotion, c.round_number,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM conversations c
    WHERE c.embedding IS NOT NULL
        AND c.model_channel = filter_channel
        AND (
            filter_scene IS NULL
            OR filter_scene = 'all'
            OR c.scene_type = filter_scene
            OR (filter_scene = 'daily' AND c.scene_type IN ('daily', 'plot'))
        )
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============ 第五段：修改 RPC 函数 search_summaries_v2 ============
CREATE OR REPLACE FUNCTION search_summaries_v2(
    query_embedding vector(1024),
    match_count int DEFAULT 3,
    filter_scene text DEFAULT 'daily',
    filter_channel text DEFAULT 'deepseek'
)
RETURNS TABLE(
    id uuid,
    summary text,
    created_at timestamptz,
    scene_type text,
    topic text,
    start_round int,
    end_round int,
    similarity float
)
LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id, s.summary, s.created_at,
        s.scene_type, s.topic, s.start_round, s.end_round,
        1 - (s.embedding <=> query_embedding) AS similarity
    FROM summaries s
    WHERE s.embedding IS NOT NULL
        AND s.model_channel = filter_channel
        AND (
            filter_scene IS NULL
            OR filter_scene = 'all'
            OR s.scene_type = filter_scene
            OR (filter_scene = 'daily' AND s.scene_type IN ('daily', 'plot'))
        )
    ORDER BY s.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- ============ 验证 ============
-- 执行完毕后，运行以下查询确认字段已添加：
-- SELECT column_name, data_type, column_default
-- FROM information_schema.columns
-- WHERE table_name IN ('conversations', 'summaries')
--   AND column_name = 'model_channel';
