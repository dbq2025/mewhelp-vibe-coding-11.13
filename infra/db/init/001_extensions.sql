-- 初始化扩展：向量检索 + 模糊匹配（仅首次创建数据卷时执行）
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 校验：应输出 vector 与 pg_trgm 两行
SELECT extname, extversion FROM pg_extension WHERE extname IN ('vector', 'pg_trgm');
