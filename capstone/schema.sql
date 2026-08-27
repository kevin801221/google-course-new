-- Capstone Phase 1 schema：沿用 Lab 8 的 documents，補上 Capstone 要的欄位＋兩張業務表。
-- 跑法：Supabase Dashboard -> SQL Editor 貼整份執行。可重複執行（全部 if not exists / on conflict）。
-- 前提：Lab 8 的 schema.sql 已經跑過（vector extension 與 documents 表在那裡建的）。

create extension if not exists vector;

-- 1) documents：Lab 8 只有 (id, source, content, embedding)，Capstone 要 topic 與時間
create table if not exists documents (
  id        bigserial primary key,
  source    text,
  content   text not null,
  embedding vector(1536)                 -- gemini-embedding-2 截斷至 1536 維
);
alter table documents add column if not exists topic      text default '';
alter table documents add column if not exists created_at timestamptz default now();

create index if not exists documents_embedding_idx on documents using hnsw (embedding vector_cosine_ops);
create index if not exists documents_topic_idx     on documents (topic);
create index if not exists documents_id_idx        on documents (id);   -- daily_digest 的 where id > $1

-- 2) notes：個人筆記（data_agent 可讀寫，走 Toolbox）
create table if not exists notes (
  id         bigserial primary key,
  title      text not null,
  body       text default '',
  tags       text[] default '{}',
  created_at timestamptz default now(),
  constraint notes_title_key unique (title)
);

-- 3) subscriptions：示範業務表（「我這個月訂閱總花費？」問的就是這張）
create table if not exists subscriptions (
  id            bigserial primary key,
  name          text not null,
  monthly_twd   integer not null check (monthly_twd >= 0),
  category      text default 'other',
  renews_on     date,
  active        boolean default true,
  constraint subscriptions_name_key unique (name)
);

insert into subscriptions (name, monthly_twd, category, renews_on, active) values
  ('Google AI Pro',      650,  'ai',        date '2026-09-03', true),
  ('GitHub Copilot',     320,  'dev',       date '2026-09-11', true),
  ('Supabase Pro',       800,  'infra',     date '2026-09-01', true),
  ('Netflix 標準',        390,  'media',     date '2026-09-18', true),
  ('Spotify 個人',        149,  'media',     date '2026-09-22', true),
  ('Notion Plus',        320,  'productivity', date '2026-09-07', false)
on conflict on constraint subscriptions_name_key do nothing;

insert into notes (title, body, tags) values
  ('A2A 1.0 重點', 'Agent Card 在 /.well-known/agent-card.json；Task 有狀態機；跨框架委派用 SendMessage。', '{"protocol","a2a"}'),
  ('Cloud Run 冷啟動', '容器瘦身最有效；min-instances=1 要付錢；scale-to-zero 的代價就是第一次慢。', '{"gcp","deploy"}')
on conflict on constraint notes_title_key do nothing;

-- 4) 驗收查詢：這三行的輸出就是 walkthrough Phase 1 步驟 1 的驗收條件
select count(*) as doc_chunks, count(distinct source) as sources from documents;
select sum(monthly_twd) as monthly_total from subscriptions where active;
select column_name from information_schema.columns
 where table_name = 'documents' and column_name in ('topic', 'created_at');
