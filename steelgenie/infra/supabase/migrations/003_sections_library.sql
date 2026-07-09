-- ============================================================
-- CalSteel — Sections Library Database Table
-- Stores profiles dimensions and unit weights for structural shape matching.
-- ============================================================

CREATE TABLE IF NOT EXISTS public.sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    designation TEXT UNIQUE NOT NULL,
    standard TEXT NOT NULL DEFAULT 'AISC', -- AISC | IS808 | BS
    section_type TEXT NOT NULL, -- W | HSS | C | L | ISMB | ISMC | ISA
    weight_per_ft NUMERIC NOT NULL, -- lbs/ft
    depth_in NUMERIC,
    flange_width_in NUMERIC,
    flange_thick_in NUMERIC,
    web_thick_in NUMERIC,
    cross_area_in2 NUMERIC,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

-- Index designations for autocomplete searches
CREATE INDEX IF NOT EXISTS idx_sections_designation ON public.sections(designation);
CREATE INDEX IF NOT EXISTS idx_sections_standard ON public.sections(standard);
CREATE INDEX IF NOT EXISTS idx_sections_type ON public.sections(section_type);

-- Seed basic US AISC Beams and Columns designations (W-shapes)
-- Format: (designation, standard, section_type, weight_per_ft, depth_in, flange_width_in, flange_thick_in, web_thick_in, cross_area_in2)
INSERT INTO public.sections (designation, standard, section_type, weight_per_ft, depth_in, flange_width_in, flange_thick_in, web_thick_in, cross_area_in2) VALUES
('W14X90', 'AISC', 'W', 90.0, 14.0, 14.5, 0.71, 0.44, 26.5),
('W14X68', 'AISC', 'W', 68.0, 14.0, 10.0, 0.72, 0.41, 20.0),
('W14X48', 'AISC', 'W', 48.0, 13.8, 8.0, 0.59, 0.34, 14.1),
('W12X96', 'AISC', 'W', 96.0, 12.7, 12.2, 0.90, 0.55, 28.2),
('W12X53', 'AISC', 'W', 53.0, 12.1, 10.0, 0.57, 0.34, 15.6),
('W12X26', 'AISC', 'W', 26.0, 12.2, 6.5, 0.38, 0.23, 7.65),
('W10X49', 'AISC', 'W', 49.0, 10.0, 10.0, 0.56, 0.34, 14.4),
('W10X30', 'AISC', 'W', 30.0, 10.5, 5.8, 0.51, 0.30, 8.84),
('W10X19', 'AISC', 'W', 19.0, 10.2, 4.0, 0.39, 0.25, 5.62),
('W8X31',  'AISC', 'W', 31.0, 8.0, 8.0, 0.43, 0.28, 9.13),
('W8X15',  'AISC', 'W', 15.0, 8.1, 4.0, 0.31, 0.24, 4.44),
('W6X9',   'AISC', 'W', 9.0,  5.9, 3.9, 0.21, 0.17, 2.68);
