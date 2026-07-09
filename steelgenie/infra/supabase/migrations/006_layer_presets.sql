-- Migration: Create layer_presets table
CREATE TABLE IF NOT EXISTS layer_presets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT timezone('utc'::text, now()) NOT NULL
);

-- Enable RLS
ALTER TABLE layer_presets ENABLE ROW LEVEL SECURITY;

-- Allow users to manage their own presets
CREATE POLICY "Users can manage their own presets"
ON layer_presets FOR ALL
USING (true)
WITH CHECK (true);
