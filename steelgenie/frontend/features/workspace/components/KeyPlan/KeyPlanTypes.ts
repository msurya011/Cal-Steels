// Shared types for the Key Plan feature (multi-page floor overlay).
// Mirrors the shape returned by GET /api/v1/projects/{project_id}/floors.

export interface KeyPlanRegistration {
  page_id: string
  floor_id: string
  tx_ft: number
  ty_ft: number
  rotation_deg: number
  ft_per_pct_x: number
  ft_per_pct_y: number
  anchor?: string | null
  confidence?: number | null
  method?: string | null // 'grid_match' | 'grid_correlation' | 'tile_fallback' | 'manual'
}

export interface KeyPlanPage {
  page_id: string
  idx: number | null
  title: string | null
  sheet_no: string | null
  zone_label: string | null
  status: string | null
  registration: KeyPlanRegistration | null
}

export interface KeyPlanFloor {
  id: string
  project_id: string
  name: string
  elevation_ft: number | null
  sort_order: number
  status?: string | null
  pages: KeyPlanPage[]
}

// SteelGenie-matching per-page palette -- cycles if a floor has more pages
// than colors, same idea as the reference's Page 31 (blue) / Page 32
// (orange) / Page 33 (green) coloring.
export const KEY_PLAN_PAGE_COLORS = ['#3B82F6', '#F97316', '#22C55E', '#A855F7', '#EC4899', '#EAB308', '#06B6D4']

export function colorForPageIdx(i: number): string {
  return KEY_PLAN_PAGE_COLORS[i % KEY_PLAN_PAGE_COLORS.length]
}
