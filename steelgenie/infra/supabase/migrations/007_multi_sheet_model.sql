-- =============================================================================
-- CalSteel Estimator — Multi-Sheet Floor Registration & Unified 3D Model (007)
-- Additive migration: no existing table is dropped, altered destructively,
-- or renamed. See docs/multi-sheet-3d-architecture.md for the full design.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- pages: new optional columns used for floor clustering
-- ---------------------------------------------------------------------------
ALTER TABLE pages ADD COLUMN IF NOT EXISTS level_name TEXT;
ALTER TABLE pages ADD COLUMN IF NOT EXISTS zone_label TEXT;

-- ---------------------------------------------------------------------------
-- floors: one structural story, may be composed of multiple sheets/pages
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS floors (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id    UUID REFERENCES projects ON DELETE CASCADE NOT NULL,
  name          TEXT NOT NULL,
  elevation_ft  FLOAT,
  sort_order    INT NOT NULL DEFAULT 0,
  status        TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'registered', 'need_review')),
  created_at    TIMESTAMPTZ DEFAULT now(),
  updated_at    TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- page_floor_links: which pages belong to which floor (1 page -> 1 floor)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS page_floor_links (
  page_id     UUID PRIMARY KEY REFERENCES pages ON DELETE CASCADE,
  floor_id    UUID REFERENCES floors ON DELETE CASCADE NOT NULL,
  zone_label  TEXT,
  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- grids: labeled grid lines, in page-local percentage coordinates
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS grids (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id     UUID REFERENCES pages ON DELETE CASCADE NOT NULL,
  axis        TEXT NOT NULL CHECK (axis IN ('x', 'y')),
  label       TEXT NOT NULL,
  position    FLOAT NOT NULL,
  confidence  FLOAT,
  source      TEXT NOT NULL DEFAULT 'ai' CHECK (source IN ('ai', 'manual')),
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- match_lines: "MATCH TO: n/SheetNo Zone" call-outs OCR'd off sheet borders
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS match_lines (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  page_id           UUID REFERENCES pages ON DELETE CASCADE NOT NULL,
  edge              TEXT NOT NULL CHECK (edge IN ('top', 'bottom', 'left', 'right')),
  raw_text          TEXT,
  target_sheet_no   TEXT,
  target_zone_label TEXT,
  confidence        FLOAT,
  created_at        TIMESTAMPTZ DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- page_registrations: resolved per-page transform into floor-global feet
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS page_registrations (
  page_id      UUID PRIMARY KEY REFERENCES pages ON DELETE CASCADE,
  floor_id     UUID REFERENCES floors ON DELETE CASCADE NOT NULL,
  tx_ft        FLOAT NOT NULL DEFAULT 0,
  ty_ft        FLOAT NOT NULL DEFAULT 0,
  rotation_deg FLOAT NOT NULL DEFAULT 0,
  ft_per_pct_x FLOAT NOT NULL DEFAULT 1,
  ft_per_pct_y FLOAT NOT NULL DEFAULT 1,
  anchor       BOOLEAN NOT NULL DEFAULT false,
  confidence   FLOAT,
  method       TEXT CHECK (method IN ('grid_match', 'match_line', 'manual', 'identity')),
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_floors_project        ON floors (project_id);
CREATE INDEX IF NOT EXISTS idx_grids_page            ON grids (page_id);
CREATE INDEX IF NOT EXISTS idx_match_lines_page       ON match_lines (page_id);
CREATE INDEX IF NOT EXISTS idx_page_floor_links_floor ON page_floor_links (floor_id);
CREATE INDEX IF NOT EXISTS idx_page_registrations_floor ON page_registrations (floor_id);

ALTER TABLE floors              ENABLE ROW LEVEL SECURITY;
ALTER TABLE page_floor_links    ENABLE ROW LEVEL SECURITY;
ALTER TABLE grids               ENABLE ROW LEVEL SECURITY;
ALTER TABLE match_lines         ENABLE ROW LEVEL SECURITY;
ALTER TABLE page_registrations  ENABLE ROW LEVEL SECURITY;

CREATE POLICY floors_policy ON floors FOR ALL USING (
  EXISTS (SELECT 1 FROM projects WHERE id = floors.project_id
    AND (owner_id = auth.uid() OR (share_scope = 'company' AND company_id = current_company_id())))
);

CREATE POLICY page_floor_links_policy ON page_floor_links FOR ALL USING (
  EXISTS (SELECT 1 FROM floors JOIN projects ON projects.id = floors.project_id
    WHERE floors.id = page_floor_links.floor_id
      AND (projects.owner_id = auth.uid() OR (projects.share_scope = 'company' AND projects.company_id = current_company_id())))
);

CREATE POLICY grids_policy ON grids FOR ALL USING (
  EXISTS (SELECT 1 FROM pages JOIN drawings ON drawings.id = pages.drawing_id
    JOIN projects ON projects.id = drawings.project_id
    WHERE pages.id = grids.page_id
      AND (projects.owner_id = auth.uid() OR (projects.share_scope = 'company' AND projects.company_id = current_company_id())))
);

CREATE POLICY match_lines_policy ON match_lines FOR ALL USING (
  EXISTS (SELECT 1 FROM pages JOIN drawings ON drawings.id = pages.drawing_id
    JOIN projects ON projects.id = drawings.project_id
    WHERE pages.id = match_lines.page_id
      AND (projects.owner_id = auth.uid() OR (projects.share_scope = 'company' AND projects.company_id = current_company_id())))
);

CREATE POLICY page_registrations_policy ON page_registrations FOR ALL USING (
  EXISTS (SELECT 1 FROM floors JOIN projects ON projects.id = floors.project_id
    WHERE floors.id = page_registrations.floor_id
      AND (projects.owner_id = auth.uid() OR (projects.share_scope = 'company' AND projects.company_id = current_company_id())))
);
