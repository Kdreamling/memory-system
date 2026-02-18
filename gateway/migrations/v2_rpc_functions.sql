-- ========================================================
-- Kelivo Memory v2.0 - pgvector RPC 搜索函数
-- 在 Supabase SQL Editor 中执行
-- ========================================================

-- ===== 1. conversations 向量搜索函数 =====
CREATE OR REPLACE FUNCTION search_conversations_v2(
    query_embedding vector(1024),
    match_count int DEFAULT 15,
    filter_scene text DEFAULT NULL
)
RETURNS TABLE (
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
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id,
        c.user_msg,
        c.assistant_msg,
        c.created_at,
        c.scene_type,
        c.topic,
        c.emotion,
        c.round_number,
        1 - (c.embedding <=> query_embedding) AS similarity
    FROM conversations c
    WHERE c.embedding IS NOT NULL
      AND (
          filter_scene IS NULL
          OR (filter_scene = 'daily' AND c.scene_type IN ('daily', 'plot'))
          OR (filter_scene != 'daily' AND c.scene_type = filter_scene)
      )
    ORDER BY c.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;


-- ===== 2. summaries 向量搜索函数 =====
CREATE OR REPLACE FUNCTION search_summaries_v2(
    query_embedding vector(1024),
    match_count int DEFAULT 15,
    filter_scene text DEFAULT NULL
)
RETURNS TABLE (
    id uuid,
    summary text,
    created_at timestamptz,
    scene_type text,
    topic text,
    start_round int,
    end_round int,
    similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        s.id,
        s.summary,
        s.created_at,
        s.scene_type,
        s.topic,
        s.start_round,
        s.end_round,
        1 - (s.embedding <=> query_embedding) AS similarity
    FROM summaries s
    WHERE s.embedding IS NOT NULL
      AND (
          filter_scene IS NULL
          OR (filter_scene = 'daily' AND s.scene_type IN ('daily', 'plot'))
          OR (filter_scene != 'daily' AND s.scene_type = filter_scene)
      )
    ORDER BY s.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;


-- ===== 验证函数已创建 =====
-- SELECT routine_name FROM information_schema.routines
-- WHERE routine_schema = 'public'
-- AND routine_name IN ('search_conversations_v2', 'search_summaries_v2');
-- 应返回2行
