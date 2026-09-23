-- SentinelCV pgvector index optimization
-- Run after migrations so face_data table exists.
-- Optional session settings:
--   SET sentinelcv.pgv_index_type = 'hnsw' | 'ivfflat';
--   SET sentinelcv.pgv_ivfflat_lists = '100';
--   SET sentinelcv.pgv_hnsw_m = '16';
--   SET sentinelcv.pgv_hnsw_ef_construction = '64';

DO $$
DECLARE
    index_type text := current_setting('sentinelcv.pgv_index_type', true);
    ivfflat_lists text := current_setting('sentinelcv.pgv_ivfflat_lists', true);
    hnsw_m text := current_setting('sentinelcv.pgv_hnsw_m', true);
    hnsw_ef_construction text := current_setting('sentinelcv.pgv_hnsw_ef_construction', true);
    lists_value int := COALESCE(NULLIF(ivfflat_lists, '')::int, 100);
    m_value int := COALESCE(NULLIF(hnsw_m, '')::int, 16);
    ef_value int := COALESCE(NULLIF(hnsw_ef_construction, '')::int, 64);
BEGIN
    IF index_type IS NULL OR index_type = '' THEN
        index_type := 'hnsw';
    END IF;

    IF index_type = 'ivfflat' THEN
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS face_data_embedding_ivfflat_idx ON face_data USING ivfflat (embedding vector_cosine_ops) WITH (lists=%s);',
            lists_value
        );
    ELSE
        EXECUTE format(
            'CREATE INDEX IF NOT EXISTS face_data_embedding_hnsw_idx ON face_data USING hnsw (embedding vector_cosine_ops) WITH (m=%s, ef_construction=%s);',
            m_value,
            ef_value
        );
    END IF;
END $$;

ANALYZE face_data;
