-- =============================================================================
-- CalSteel Estimator — Full Schema Migration (002)
-- Extends 001_initial.sql with the complete production schema.
-- Run in: Supabase Dashboard → SQL Editor → New Query → Run
--
-- IMPORTANT: Run 001_initial.sql first OR run this file standalone (it drops
-- the old 4 tables and recreates everything from scratch).
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- DROP OLD TABLES (replaced by new schema)
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS jobs      CASCADE;
DROP TABLE IF EXISTS members   CASCADE;
DROP TABLE IF EXISTS drawings  CASCADE;
DROP TABLE IF EXISTS projects  CASCADE;

-- ---------------------------------------------------------------------------
-- TENANCY
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS companies (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  email       TEXT,
  address     TEXT,
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  id          UUID PRIMARY KEY REFERENCES auth.users ON DELETE CASCADE,
  company_id  UUID REFERENCES companies ON DELETE SET NULL,
  name        TEXT,
  email       TEXT NOT NULL,
  role        TEXT NOT NULL DEFAULT 'estimator'
              CHECK (role IN ('admin','manager','estimator','viewer')),
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS licenses (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id       UUID REFERENCES companies NOT NULL,
  type             TEXT NOT NULL DEFAULT 'trial',
  valid_until      TIMESTAMPTZ,
  assigned_user_id UUID REFERENCES users ON DELETE SET NULL,
  created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS invitations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id  UUID REFERENCES companies NOT NULL,
  email       TEXT NOT NULL,
  role        TEXT NOT NULL DEFAULT 'estimator',
  status      TEXT NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','accepted','expired')),
  invited_by  UUID REFERENCES users ON DELETE SET NULL,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS activity_logs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id  UUID REFERENCES companies,
  user_id     UUID REFERENCES users ON DELETE SET NULL,
  action      TEXT NOT NULL,
  entity      TEXT,
  entity_id   UUID,
  ts          TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- PROJECTS & DOCUMENTS
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS folders (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id  UUID REFERENCES companies NOT NULL,
  name        TEXT NOT NULL,
  owner_id    UUID REFERENCES users ON DELETE SET NULL,
  created_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id       UUID REFERENCES companies,
  owner_id         UUID REFERENCES users NOT NULL,
  folder_id        UUID REFERENCES folders ON DELETE SET NULL,
  name             TEXT NOT NULL,
  number           TEXT,
  status           TEXT NOT NULL DEFAULT 'in_progress'
                   CHECK (status IN ('in_progress','completed','on_hold','archived')),
  design_standard  TEXT NOT NULL DEFAULT 'AISC',
  unit_system      TEXT NOT NULL DEFAULT 'imperial'
                   CHECK (unit_system IN ('imperial','metric')),
  location         TEXT,
  description      TEXT,
  pinned           BOOLEAN NOT NULL DEFAULT false,
  share_scope      TEXT NOT NULL DEFAULT 'private'
                   CHECK (share_scope IN ('private','company')),
  created_at       TIMESTAMPTZ DEFAULT now(),
  updated_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS project_shares (
  project_id  UUID REFERENCES projects ON DELETE CASCADE NOT NULL,
  user_id     UUID REFERENCES users ON DELETE CASCADE NOT NULL,
  permission  TEXT NOT NULL DEFAULT 'viewer'
              CHECK (permission IN ('viewer','editor')),
  PRIMARY KEY (project_id, user_id)
);

CREATE TABLE IF NOT EXISTS drawings (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID REFERENCES projects ON DELETE CASCADE NOT NULL,
  filename    TEXT NOT NULL,
  storage_key TEXT NOT NULL,
  page_count  INT,
  file_size   BIGINT,
  status      TEXT NOT NULL DEFAULT 'uploaded'
              CHECK (status IN ('uploaded','ingesting','ready','error')),
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS pages (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  drawing_id   UUID REFERENCES drawings ON DELETE CASCADE NOT NULL,
  idx          INT NOT NULL,
  sheet_no     TEXT,
  title        TEXT,
  scale_num    FLOAT,
  scale_label  TEXT,
  tos_ft       FLOAT,
  status       TEXT NOT NULL DEFAULT 'not_started'
               CHECK (status IN ('not_started','estimating','built','need_review')),
  thumb_key    TEXT,
  image_key    TEXT,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now(),
  UNIQUE (drawing_id, idx)
);

-- ---------------------------------------------------------------------------
-- TAKEOFF
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS members (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id     UUID REFERENCES pages ON DELETE CASCADE NOT NULL,
  kind        TEXT NOT NULL DEFAULT 'beam'
              CHECK (kind IN ('beam','column','vbrace','hbrace','joist')),
  section     TEXT,
  grade       TEXT DEFAULT 'A992',
  rotation    FLOAT DEFAULT 0,
  status      TEXT NOT NULL DEFAULT 'active'
              CHECK (status IN ('active','need_review','verified','rejected','excluded')),
  source      TEXT NOT NULL DEFAULT 'ai'
              CHECK (source IN ('ai','manual')),
  geometry    JSONB NOT NULL DEFAULT '{}',
  confidence  FLOAT,
  length_ft   FLOAT,
  piecemark   TEXT,
  reviewed_by UUID REFERENCES users ON DELETE SET NULL,
  reviewed_at TIMESTAMPTZ,
  created_by  UUID REFERENCES users ON DELETE SET NULL,
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS annotations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id     UUID REFERENCES pages ON DELETE CASCADE NOT NULL,
  kind        TEXT NOT NULL,
  payload     JSONB NOT NULL DEFAULT '{}',
  author_id   UUID REFERENCES users ON DELETE SET NULL,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- ENGINEERING
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS configurations (
  project_id   UUID PRIMARY KEY REFERENCES projects ON DELETE CASCADE,
  payload      JSONB NOT NULL DEFAULT '{}',
  ai_rationale JSONB,
  revision     INT NOT NULL DEFAULT 0,
  applied_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS jobs (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id      UUID REFERENCES projects ON DELETE CASCADE,
  drawing_id      UUID REFERENCES drawings ON DELETE CASCADE,
  page_id         UUID REFERENCES pages ON DELETE CASCADE,
  type            TEXT NOT NULL
                  CHECK (type IN ('ingest','analyse','build','export')),
  status          TEXT NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued','running','done','failed')),
  progress        INT NOT NULL DEFAULT 0,
  message         TEXT,
  error           TEXT,
  result          JSONB,
  engine_version  TEXT,
  created_by      UUID REFERENCES users ON DELETE SET NULL,
  started_at      TIMESTAMPTZ,
  finished_at     TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS column_groups (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID REFERENCES projects ON DELETE CASCADE NOT NULL,
  name        TEXT NOT NULL,
  column_ids  UUID[],
  splice      JSONB,
  base_plate  JSONB,
  anchors     JSONB,
  warnings    JSONB,
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS braced_frames (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID REFERENCES projects ON DELETE CASCADE NOT NULL,
  name        TEXT NOT NULL,
  geometry    JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- BOM
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS bom_items (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id   UUID REFERENCES projects ON DELETE CASCADE NOT NULL,
  build_id     UUID REFERENCES jobs ON DELETE CASCADE,
  piecemark    TEXT,
  category     TEXT,
  qty          INT NOT NULL DEFAULT 1,
  section_type TEXT,
  section      TEXT,
  length_in    NUMERIC,
  grade        TEXT,
  labor_code   TEXT,
  weight_lbs   NUMERIC,
  camber       FLOAT DEFAULT 0,
  cope         INT DEFAULT 0,
  holes        INT DEFAULT 0,
  weld_studs   INT DEFAULT 0,
  status       TEXT DEFAULT 'active',
  sequence     INT,
  paint        TEXT,
  is_main      BOOLEAN NOT NULL DEFAULT true,
  custom       JSONB,
  created_at   TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS labor_codes (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  company_id      UUID REFERENCES companies ON DELETE CASCADE,
  project_id      UUID REFERENCES projects ON DELETE CASCADE,
  code            TEXT NOT NULL,
  description     TEXT,
  category        TEXT,
  shape_pattern   TEXT,
  created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS export_jobs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  UUID REFERENCES projects ON DELETE CASCADE NOT NULL,
  format      TEXT NOT NULL
              CHECK (format IN ('pdf','ifc','epm_xlsx','kiss','bom_xlsx','bom_csv')),
  status      TEXT NOT NULL DEFAULT 'queued'
              CHECK (status IN ('queued','running','done','failed')),
  storage_key TEXT,
  error       TEXT,
  created_by  UUID REFERENCES users ON DELETE SET NULL,
  created_at  TIMESTAMPTZ DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS notifications (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID REFERENCES users ON DELETE CASCADE NOT NULL,
  type        TEXT NOT NULL DEFAULT 'info',
  title       TEXT NOT NULL,
  body        TEXT,
  read_at     TIMESTAMPTZ,
  entity      TEXT,
  entity_id   UUID,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- INDEXES
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_projects_owner      ON projects (owner_id);
CREATE INDEX IF NOT EXISTS idx_projects_company    ON projects (company_id);
CREATE INDEX IF NOT EXISTS idx_projects_updated_at ON projects (updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_drawings_project    ON drawings (project_id);
CREATE INDEX IF NOT EXISTS idx_pages_drawing       ON pages (drawing_id);
CREATE INDEX IF NOT EXISTS idx_members_page        ON members (page_id);
CREATE INDEX IF NOT EXISTS idx_members_kind_status ON members (page_id, kind, status);
CREATE INDEX IF NOT EXISTS idx_jobs_project        ON jobs (project_id);
CREATE INDEX IF NOT EXISTS idx_jobs_type_status    ON jobs (type, status);
CREATE INDEX IF NOT EXISTS idx_bom_project_cat     ON bom_items (project_id, category);
CREATE INDEX IF NOT EXISTS idx_notif_user_unread   ON notifications (user_id, read_at) WHERE read_at IS NULL;

-- ---------------------------------------------------------------------------
-- ROW LEVEL SECURITY
-- ---------------------------------------------------------------------------
ALTER TABLE companies       ENABLE ROW LEVEL SECURITY;
ALTER TABLE users           ENABLE ROW LEVEL SECURITY;
ALTER TABLE licenses        ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitations     ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_logs   ENABLE ROW LEVEL SECURITY;
ALTER TABLE folders         ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects        ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_shares  ENABLE ROW LEVEL SECURITY;
ALTER TABLE drawings        ENABLE ROW LEVEL SECURITY;
ALTER TABLE pages           ENABLE ROW LEVEL SECURITY;
ALTER TABLE members         ENABLE ROW LEVEL SECURITY;
ALTER TABLE annotations     ENABLE ROW LEVEL SECURITY;
ALTER TABLE configurations  ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs            ENABLE ROW LEVEL SECURITY;
ALTER TABLE column_groups   ENABLE ROW LEVEL SECURITY;
ALTER TABLE braced_frames   ENABLE ROW LEVEL SECURITY;
ALTER TABLE bom_items       ENABLE ROW LEVEL SECURITY;
ALTER TABLE labor_codes     ENABLE ROW LEVEL SECURITY;
ALTER TABLE export_jobs     ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications   ENABLE ROW LEVEL SECURITY;

-- Helper function
CREATE OR REPLACE FUNCTION current_company_id()
RETURNS UUID LANGUAGE sql STABLE
AS $$ SELECT company_id FROM users WHERE id = auth.uid() $$;

-- Policies
CREATE POLICY companies_policy ON companies FOR ALL USING (id = current_company_id());
CREATE POLICY users_policy ON users FOR ALL USING (id = auth.uid() OR company_id = current_company_id());
CREATE POLICY licenses_policy ON licenses FOR ALL USING (company_id = current_company_id());
CREATE POLICY invitations_policy ON invitations FOR ALL USING (company_id = current_company_id());
CREATE POLICY activity_policy ON activity_logs FOR ALL USING (company_id = current_company_id());
CREATE POLICY folders_policy ON folders FOR ALL USING (company_id = current_company_id());

CREATE POLICY projects_policy ON projects FOR ALL USING (
  owner_id = auth.uid()
  OR (share_scope = 'company' AND company_id = current_company_id())
  OR EXISTS (SELECT 1 FROM project_shares WHERE project_id = projects.id AND user_id = auth.uid())
);

CREATE POLICY shares_policy ON project_shares FOR ALL USING (
  EXISTS (SELECT 1 FROM projects WHERE id = project_shares.project_id AND owner_id = auth.uid())
);

CREATE POLICY drawings_policy ON drawings FOR ALL USING (
  EXISTS (SELECT 1 FROM projects WHERE id = drawings.project_id
    AND (owner_id = auth.uid() OR (share_scope = 'company' AND company_id = current_company_id())
      OR EXISTS (SELECT 1 FROM project_shares WHERE project_id = projects.id AND user_id = auth.uid())))
);

CREATE POLICY pages_policy ON pages FOR ALL USING (
  EXISTS (SELECT 1 FROM drawings JOIN projects ON projects.id = drawings.project_id
    WHERE drawings.id = pages.drawing_id
      AND (projects.owner_id = auth.uid() OR (projects.share_scope = 'company' AND projects.company_id = current_company_id())))
);

CREATE POLICY members_policy ON members FOR ALL USING (
  EXISTS (SELECT 1 FROM pages JOIN drawings ON drawings.id = pages.drawing_id
    JOIN projects ON projects.id = drawings.project_id
    WHERE pages.id = members.page_id
      AND (projects.owner_id = auth.uid() OR (projects.share_scope = 'company' AND projects.company_id = current_company_id())))
);

CREATE POLICY annotations_policy ON annotations FOR ALL USING (
  EXISTS (SELECT 1 FROM pages JOIN drawings ON drawings.id = pages.drawing_id
    JOIN projects ON projects.id = drawings.project_id
    WHERE pages.id = annotations.page_id AND projects.owner_id = auth.uid())
);

CREATE POLICY config_policy ON configurations FOR ALL USING (
  EXISTS (SELECT 1 FROM projects WHERE id = configurations.project_id AND owner_id = auth.uid())
);

CREATE POLICY jobs_policy ON jobs FOR ALL USING (
  project_id IS NULL OR EXISTS (SELECT 1 FROM projects WHERE id = jobs.project_id
    AND (owner_id = auth.uid() OR (share_scope = 'company' AND company_id = current_company_id())))
);

CREATE POLICY col_groups_policy ON column_groups FOR ALL USING (
  EXISTS (SELECT 1 FROM projects WHERE id = column_groups.project_id AND owner_id = auth.uid())
);

CREATE POLICY braces_policy ON braced_frames FOR ALL USING (
  EXISTS (SELECT 1 FROM projects WHERE id = braced_frames.project_id AND owner_id = auth.uid())
);

CREATE POLICY bom_policy ON bom_items FOR ALL USING (
  EXISTS (SELECT 1 FROM projects WHERE id = bom_items.project_id AND owner_id = auth.uid())
);

CREATE POLICY labor_codes_policy ON labor_codes FOR ALL USING (
  company_id = current_company_id()
  OR project_id IN (SELECT id FROM projects WHERE owner_id = auth.uid())
);

CREATE POLICY exports_policy ON export_jobs FOR ALL USING (
  EXISTS (SELECT 1 FROM projects WHERE id = export_jobs.project_id AND owner_id = auth.uid())
);

CREATE POLICY notif_policy ON notifications FOR ALL USING (user_id = auth.uid());

-- ---------------------------------------------------------------------------
-- TRIGGERS
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END; $$;

DO $$ DECLARE t TEXT;
BEGIN
  FOREACH t IN ARRAY ARRAY['companies','users','projects','drawings','pages','members','column_groups','braced_frames']
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_updated_at ON %I;
      CREATE TRIGGER trg_%I_updated_at BEFORE UPDATE ON %I
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();', t,t,t,t);
  END LOOP;
END; $$;

-- Auto-create user record on Supabase sign-up
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
BEGIN
  INSERT INTO public.users (id, email, name)
  VALUES (NEW.id, NEW.email, COALESCE(NEW.raw_user_meta_data->>'name', split_part(NEW.email,'@',1)))
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END; $$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION handle_new_user();
