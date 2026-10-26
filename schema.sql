-- ============================================================
-- SALON BOOKING SYSTEM — Run this in Supabase SQL Editor
-- ============================================================

create table if not exists salons (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,
  phone      text,
  created_at timestamptz default now()
);

create table if not exists barbers (
  id         uuid primary key default gen_random_uuid(),
  salon_id   uuid references salons(id) on delete cascade,
  name       text not null,
  phone      text,
  created_at timestamptz default now()
);

create table if not exists bookings (
  id             uuid primary key default gen_random_uuid(),
  salon_id       uuid references salons(id) on delete cascade,
  barber_id      uuid references barbers(id) on delete cascade,
  customer_name  text not null,
  customer_phone text not null,
  date           date not null,
  slot_time      text not null,
  status         text default 'confirmed' check (status in ('confirmed','cancelled','completed')),
  created_at     timestamptz default now()
);

create table if not exists blocked_slots (
  id         uuid primary key default gen_random_uuid(),
  barber_id  uuid references barbers(id) on delete cascade,
  date       date not null,
  slot_time  text not null,
  reason     text,
  created_at timestamptz default now()
);

create unique index if not exists unique_confirmed_booking
  on bookings (barber_id, date, slot_time)
  where status = 'confirmed';

-- Seed data
insert into salons (id, name, phone) values
  ('11111111-1111-1111-1111-111111111111', 'Style Hub Salon', '+919999999999')
on conflict (id) do nothing;

insert into barbers (salon_id, name, phone) values
  ('11111111-1111-1111-1111-111111111111', 'Raj',   '+919876543210'),
  ('11111111-1111-1111-1111-111111111111', 'Arjun', '+919876543211'),
  ('11111111-1111-1111-1111-111111111111', 'Sunil', '+919876543212')
on conflict do nothing;
