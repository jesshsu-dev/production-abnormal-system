-- 生產異常通報系統 V1.1 Enterprise
-- Supabase SQL Editor 一次執行
-- 時區資料使用 timestamptz；前端顯示 Asia/Taipei

create extension if not exists pgcrypto;

-- 1) 使用者延伸資料
create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text not null default '',
  role text not null default '生產' check (role in ('生產','工程','品保','主管','管理員')),
  department text not null default '',
  email text not null default '',
  line_user_id text not null default '',
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Auth 建立使用者時自動建立 profile
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles(id, display_name, email)
  values (
    new.id,
    coalesce(new.raw_user_meta_data ->> 'display_name', split_part(coalesce(new.email,''),'@',1)),
    coalesce(new.email,'')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
after insert on auth.users
for each row execute procedure public.handle_new_user();

-- 若 Auth 使用者早於本 SQL 已存在，補 profiles
insert into public.profiles(id, display_name, email)
select id, split_part(coalesce(email,''),'@',1), coalesce(email,'')
from auth.users
on conflict (id) do nothing;

-- 2) 每日異常編號 counter
create table if not exists public.daily_counters (
  counter_date date primary key,
  seq integer not null default 0
);

create or replace function public.next_abnormal_no()
returns text
language plpgsql
security definer set search_path=public
as $$
declare
  d date := (now() at time zone 'Asia/Taipei')::date;
  n integer;
begin
  insert into public.daily_counters(counter_date, seq)
  values (d, 1)
  on conflict (counter_date)
  do update set seq = public.daily_counters.seq + 1
  returning seq into n;
  return to_char(d,'YYYYMMDD') || lpad(n::text,3,'0');
end;
$$;

-- 3) 異常案件
create table if not exists public.incidents (
  id uuid primary key default gen_random_uuid(),
  abnormal_no text unique,
  abnormal_type text not null,
  work_order text not null,
  model text not null,
  work_qty integer not null default 0 check (work_qty >= 0),
  defect_qty integer not null default 0 check (defect_qty >= 0),
  material_no text not null default '',
  process_name text not null,
  reporter_id uuid not null references public.profiles(id),
  reporter_name text not null,
  report_time timestamptz not null default now(),
  receiver_id uuid references public.profiles(id),
  receiver_name text,
  receive_time timestamptz,
  abnormal_desc text not null,
  replier_id uuid references public.profiles(id),
  replier_name text,
  reply_time timestamptz,
  process_progress text not null default '待受理'
    check (process_progress in ('待受理','處理中','待確認','已結案')),
  process_method text,
  finish_time timestamptz,
  main_cause text check (main_cause is null or main_cause in ('人','機','料','法','測','環')),
  cause_category text,
  sub_cause text,
  total_defect_qty integer not null default 0 check (total_defect_qty >= 0),
  root_cause text,
  closer_id uuid references public.profiles(id),
  closer_name text,
  close_time timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create or replace function public.incidents_before_insert()
returns trigger language plpgsql security definer set search_path=public
as $$
begin
  if new.abnormal_no is null or btrim(new.abnormal_no)='' then
    new.abnormal_no := public.next_abnormal_no();
  end if;
  new.report_time := coalesce(new.report_time, now());
  return new;
end; $$;

drop trigger if exists trg_incidents_before_insert on public.incidents;
create trigger trg_incidents_before_insert
before insert on public.incidents
for each row execute procedure public.incidents_before_insert();

create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at=now(); return new; end; $$;

drop trigger if exists trg_incidents_updated on public.incidents;
create trigger trg_incidents_updated
before update on public.incidents
for each row execute procedure public.touch_updated_at();

-- 4) 催辦規則
create table if not exists public.notification_rules (
  level integer primary key check (level between 1 and 5),
  threshold_minutes integer not null,
  color text not null,
  target_label text not null,
  enabled boolean not null default true
);

insert into public.notification_rules(level,threshold_minutes,color,target_label,enabled) values
(1,5,'綠色','工程/品保相關人員',true),
(2,10,'綠色','工程/品保相關人員',true),
(3,15,'藍色','單位主管',true),
(4,60,'黃色','上級主管',true),
(5,120,'紅色','最高主管',true)
on conflict(level) do update set
threshold_minutes=excluded.threshold_minutes,
color=excluded.color,target_label=excluded.target_label;

create table if not exists public.notification_members (
  level integer not null references public.notification_rules(level) on delete cascade,
  user_id uuid not null references public.profiles(id) on delete cascade,
  primary key(level,user_id)
);

create table if not exists public.notification_logs (
  id bigint generated by default as identity primary key,
  incident_id uuid not null references public.incidents(id) on delete cascade,
  abnormal_no text not null,
  level integer not null,
  notify_time timestamptz not null default now(),
  notify_target text not null default '',
  email_result text not null default '',
  line_result text not null default '',
  note text not null default '',
  unique(incident_id,level)
);

-- 5) 角色 helper
create or replace function public.current_app_role()
returns text language sql stable security definer set search_path=public
as $$
  select role from public.profiles where id=auth.uid() and active=true
$$;

-- 6) RLS
alter table public.profiles enable row level security;
alter table public.incidents enable row level security;
alter table public.notification_rules enable row level security;
alter table public.notification_members enable row level security;
alter table public.notification_logs enable row level security;

drop policy if exists profiles_read on public.profiles;
create policy profiles_read on public.profiles
for select to authenticated using (active=true or id=auth.uid());

drop policy if exists profiles_admin_update on public.profiles;
create policy profiles_admin_update on public.profiles
for update to authenticated
using (public.current_app_role() in ('主管','管理員'))
with check (public.current_app_role() in ('主管','管理員'));

drop policy if exists incidents_read on public.incidents;
create policy incidents_read on public.incidents
for select to authenticated using (true);

drop policy if exists incidents_insert on public.incidents;
create policy incidents_insert on public.incidents
for insert to authenticated
with check (reporter_id=auth.uid());

drop policy if exists incidents_handle_update on public.incidents;
create policy incidents_handle_update on public.incidents
for update to authenticated
using (public.current_app_role() in ('工程','品保','主管','管理員'))
with check (public.current_app_role() in ('工程','品保','主管','管理員'));

drop policy if exists rules_read on public.notification_rules;
create policy rules_read on public.notification_rules
for select to authenticated using (true);

drop policy if exists rules_admin on public.notification_rules;
create policy rules_admin on public.notification_rules
for all to authenticated
using (public.current_app_role() in ('主管','管理員'))
with check (public.current_app_role() in ('主管','管理員'));

drop policy if exists members_read on public.notification_members;
create policy members_read on public.notification_members
for select to authenticated using (true);

drop policy if exists members_admin on public.notification_members;
create policy members_admin on public.notification_members
for all to authenticated
using (public.current_app_role() in ('主管','管理員'))
with check (public.current_app_role() in ('主管','管理員'));

drop policy if exists logs_read on public.notification_logs;
create policy logs_read on public.notification_logs
for select to authenticated using (true);

-- notification_logs 不開放 authenticated insert/update/delete；
-- worker.py 使用 SUPABASE_SERVICE_ROLE_KEY，service role 會繞過 RLS。

-- 7) 索引
create index if not exists idx_incidents_report_time on public.incidents(report_time desc);
create index if not exists idx_incidents_progress on public.incidents(process_progress);
create index if not exists idx_incidents_receive_time on public.incidents(receive_time);
create index if not exists idx_logs_incident on public.notification_logs(incident_id);

-- 執行後請至 Table Editor > profiles：
-- 1. 修改 display_name / role / department
-- 2. 填入通知人員 email / line_user_id
-- 3. 第一位管理員請將 role 改為 '管理員'
