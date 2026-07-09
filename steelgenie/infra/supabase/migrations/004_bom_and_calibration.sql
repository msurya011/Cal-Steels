-- ============================================================
-- CalSteel — BOM Items and Scale Calibration Schema
-- Creates project-level bill of materials tracking and page scale columns.
-- ============================================================

-- 1. Add scale_ratio_px_ft to public.pages
ALTER TABLE public.pages 
ADD COLUMN IF NOT EXISTS scale_ratio_px_ft NUMERIC;

-- 2. Create the bom_items database table
CREATE TABLE IF NOT EXISTS public.bom_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    page_id UUID REFERENCES public.pages(id) ON DELETE SET NULL,
    member_id UUID REFERENCES public.members(id) ON DELETE CASCADE,
    piecemark TEXT NOT NULL,
    qty INT NOT NULL DEFAULT 1,
    section TEXT NOT NULL,
    length_in INT NOT NULL, -- length in inches
    weight_lbs DOUBLE PRECISION NOT NULL, -- total calculated weight in lbs
    grade TEXT NOT NULL DEFAULT 'A992', -- e.g. A992, A36
    labor_code TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

-- Enable RLS and chain policies by project ownership
ALTER TABLE public.bom_items ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can view BOM items belonging to their projects" ON public.bom_items
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.projects p
            WHERE p.id = bom_items.project_id AND p.owner_id = auth.uid()
        )
    );

CREATE POLICY "Users can edit BOM items belonging to their projects" ON public.bom_items
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.projects p
            WHERE p.id = bom_items.project_id AND p.owner_id = auth.uid()
        )
    );

-- Indices for performance validation queries
CREATE INDEX IF NOT EXISTS idx_bom_items_project ON public.bom_items(project_id);
CREATE INDEX IF NOT EXISTS idx_bom_items_page ON public.bom_items(page_id);
CREATE INDEX IF NOT EXISTS idx_bom_items_member ON public.bom_items(member_id);
