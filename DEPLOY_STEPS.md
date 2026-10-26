# Deploy to Railway — Step by Step

## PART A — Supabase (database) — 5 minutes

1. Go to https://supabase.com → Sign up free
2. Click "New project" → name it "salon-booking" → set a password → Create
3. Wait ~2 min for it to load
4. Click "SQL Editor" in the left sidebar
5. Copy everything from `schema.sql` → paste → click "Run"
6. You should see "Success. No rows returned"
7. Go to Settings → API
8. Copy "Project URL" → save it
9. Copy "anon public" key → save it


## PART B — GitHub (code hosting) — 3 minutes

1. Go to https://github.com → Sign up free
2. Click "+" top right → "New repository"
3. Name it "salon-booking" → keep it Public → click "Create repository"
4. On the next page, click "uploading an existing file"
5. Drag ALL the files from this zip into the upload area:
   - main.py
   - database.py
   - requirements.txt
   - Procfile
   - railway.json
   - schema.sql
   - routers/ (drag the whole folder)
6. Scroll down → click "Commit changes"


## PART C — Railway (live server) — 2 minutes

1. Go to https://railway.app → Sign up with GitHub
2. Click "New Project" → "Deploy from GitHub repo"
3. Select your "salon-booking" repo → click Deploy
4. Wait ~1 minute for it to build
5. Click your project → go to "Variables" tab
6. Add these two variables:
   - SUPABASE_URL = (paste your Supabase Project URL)
   - SUPABASE_KEY = (paste your Supabase anon key)
7. Railway will auto-redeploy
8. Click "Settings" → "Domains" → "Generate Domain"
9. Your live URL will look like: https://salon-booking-xxxx.railway.app


## PART D — Test it

Open your live URL + /docs in browser:
https://salon-booking-xxxx.railway.app/docs

Try GET /api/barbers with:
  salon_id = 11111111-1111-1111-1111-111111111111

You should see Raj, Arjun, Sunil returned. Phase 1 done!
