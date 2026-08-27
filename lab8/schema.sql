-- Lab 8 schema：hotels 表（投影片 8.2）＋ pgvector（8.5）
-- 跑法：Supabase Dashboard -> SQL Editor 貼整份執行。可重複執行（都有 if not exists / on conflict）。
-- 這張表 Lab 9 / Lab 10 / M11 Capstone 都會用，欄位一次定對。

-- 1) pgvector 擴充（Supabase 免費層內建，只是預設沒啟用）
create extension if not exists vector;

-- 2) 主表
create table if not exists hotels (
  id          bigserial primary key,
  name        text not null,
  city        text not null,
  price_twd   integer not null check (price_twd > 0),
  rating      numeric(2,1) default 4.0 check (rating >= 0 and rating <= 5),
  tags        text[] default '{}',
  description text,                      -- 語意搜尋要吃的原文（加分題 A）
  embedding   vector(1536),              -- gemini-embedding-2 截斷至 1536 維
  created_at  timestamptz default now(),
  constraint hotels_name_city_key unique (name, city)   -- 種資料重跑不會變兩倍
);

-- 3) 索引：一個給 SQL 過濾（Toolbox 的 search-hotels-by-city），一個給向量排序
create index if not exists hotels_city_price_idx
  on hotels (city, price_twd);

create index if not exists hotels_embedding_idx
  on hotels using hnsw (embedding vector_cosine_ops);

-- 4) 種資料：五個城市、價位從 1200 到 6800，故意跨越 3000 這條預算線
insert into hotels (name, city, price_twd, rating, tags, description) values
  ('Sakura Inn',      'Tokyo',   2800, 4.3, '{"近車站","含早餐"}',       '新宿站步行 4 分鐘的小型旅館，房間不大但很安靜，含日式早餐。'),
  ('Shibuya Stay',    'Tokyo',   4200, 4.6, '{"新開幕","高樓景觀"}',     '澀谷十字路口旁的新開幕設計旅店，高樓層看得到夜景，適合情侶。'),
  ('Ueno Capsule',    'Tokyo',   1200, 3.8, '{"背包客","24小時櫃台"}',   '上野的膠囊旅館，最便宜的選擇，共用衛浴，深夜也能入住。'),
  ('Ginza Grand',     'Tokyo',   6800, 4.8, '{"五星","溫泉"}',           '銀座的五星飯店，頂樓有溫泉大浴場與米其林餐廳，服務細緻。'),
  ('Osaka Base',      'Osaka',   1900, 4.1, '{"背包客"}',                '難波的背包客棧，交通方便價格便宜，適合只是要有張床的旅人。'),
  ('Namba Family',    'Osaka',   3600, 4.4, '{"親子","四人房"}',         '難波的家庭式旅館，有四人房與嬰兒床，樓下就是超市。'),
  ('Kyoto Machiya',   'Kyoto',   5200, 4.7, '{"町屋","榻榻米"}',         '祇園旁的百年町屋改建，全棟包棟，榻榻米與小庭院，適合安靜度假。'),
  ('Kyoto Station Hub','Kyoto',  2400, 4.0, '{"近車站","自助洗衣"}',     '京都車站正對面的商務旅館，房間小但機能齊全，有自助洗衣。'),
  ('Sapporo Snow',    'Sapporo', 3100, 4.2, '{"含早餐","雪祭"}',         '札幌大通公園旁，冬天走去雪祭會場五分鐘，含北海道食材早餐。'),
  ('Taipei Riverside','Taipei',  2200, 4.1, '{"近捷運","健身房"}',       '大稻埕河邊的旅館，近捷運北門站，有健身房與屋頂酒吧。')
on conflict on constraint hotels_name_city_key do nothing;

-- 5) 驗收查詢：這三行的輸出就是 walkthrough 步驟 1 的驗收條件
select count(*) as total from hotels;
select city, count(*) as n, round(avg(price_twd)) as avg_price from hotels group by city order by avg_price;
select name, price_twd, rating from hotels where city = 'Tokyo' and price_twd <= 3000 order by rating desc;

-- 6) （選配，加分題 A／Capstone 用）通用知識庫表，投影片 8.5 的 documents
--    Lab 8 主線不需要，但 Lab 9 之後要放課程文件時直接用這張。
create table if not exists documents (
  id        bigserial primary key,
  source    text,
  content   text not null,
  embedding vector(1536)
);
create index if not exists documents_embedding_idx
  on documents using hnsw (embedding vector_cosine_ops);
