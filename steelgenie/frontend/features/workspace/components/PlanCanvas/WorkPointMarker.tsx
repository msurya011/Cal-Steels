import React from 'react'

// Matches the shape returned by grid_geometry_pass.to_frontend_work_point()
// on the backend -- see GET /api/v1/pages/{page_id}/work-point.
export interface WorkPoint {
  id: string
  label: string           // always "WP"
  v_label: string         // e.g. "1"
  h_label: string         // e.g. "A"
  grid_ref: string        // e.g. "1/A"
  x: number               // normalized 0-1, same convention as GridDimension
  y: number
  outward_dx?: number     // -1 or 1 -- which way is "away from the plan" in x
  outward_dy?: number     // -1 or 1 -- which way is "away from the plan" in y
  source: string
}

interface WorkPointMarkerProps {
  workPoint: WorkPoint
}

// Renders the plan's implied origin -- the grid intersection a detailer/
// estimator would treat as "where measurements start" -- as a small target
// crosshair with an arrow pointing in from outside the plan, labeled "WP".
// This is a best-guess convention marker (first grid in each axis's own
// label sequence), not a verified stamped benchmark -- see the backend
// docstring on to_frontend_work_point for why.
export function WorkPointMarker({ workPoint }: WorkPointMarkerProps) {
  // Defense in depth: the backend already refuses to return a work point for
  // degenerate page geometry (see the pw/ph guard in to_frontend_work_point),
  // but never trust a coordinate blindly before drawing with it -- a NaN or
  // out-of-range value here would otherwise render as either nothing at all
  // (silently missing, confusing) or a marker miles off in blank space
  // (exactly the class of bug this whole feature keeps getting caught on).
  if (
    typeof workPoint.x !== 'number' || typeof workPoint.y !== 'number' ||
    !Number.isFinite(workPoint.x) || !Number.isFinite(workPoint.y)
  ) {
    return null
  }

  // Safely clamp coordinates to within visible bounds so edge boundary grids
  // don't silently fail due to rounding or slight layout offsets
  const clampedX = Math.max(0.005, Math.min(0.995, workPoint.x))
  const clampedY = Math.max(0.005, Math.min(0.995, workPoint.y))
  const cx = clampedX * 100
  const cy = clampedY * 100

  // Magenta -- deliberately NOT amber/orange. Checked against every color
  // this app already assigns meaning to: column #38BDF8 (blue), beam
  // #8B5CF6 (violet), vertical brace #D97706 (amber/orange), horizontal
  // brace #0E7490 (teal), joist #10B981 (green), unlabelled #64748B
  // (slate), dimension-line match/hover #22C55E (green), dimension-line
  // mismatch #EF4444 (red), low-confidence halo warning #F59E0B (amber).
  // An earlier amber pick for WP sat right next to the brace and
  // low-confidence-warning colors -- easy to mistake for either at a
  // glance. Magenta has no overlap with any of them.
  const WP_COLOR = '#EC4899'

  // Arrow comes in from outside the plan, on whichever side the backend says
  // is actually "away from the drawing" for this specific corner (see
  // outward_dx/outward_dy on the backend) -- a corner grid intersection is
  // often exactly where a real column/beam callout sits, so a hardcoded
  // direction eventually routes straight through that content on some sheet.
  // Falls back to up-and-left only if an older backend response is missing
  // these fields.
  const dirX = workPoint.outward_dx ?? -1
  const dirY = workPoint.outward_dy ?? -1
  const arrowLen = 6.5 // % of image width/height

  // Clamp the label's anchor point to stay inside the visible canvas. The
  // overlay SVG clips anything outside 0-100% (see OverlayLayer's
  // `overflow: hidden`), so an origin sitting very close to the edge of the
  // sheet -- normal for a real bottom-left/top-right corner grid -- would
  // otherwise push the "WP" label itself past the edge and off-screen,
  // leaving just a dangling line with no visible label. The leader still
  // starts from the clamped anchor, so it just reads as a shorter line near
  // an edge rather than an invisible label.
  const clampPct = (v: number) => Math.max(4, Math.min(96, v))
  const ax = clampPct(cx + dirX * arrowLen)
  const ay = clampPct(cy + dirY * arrowLen)

  return (
    <g style={{ pointerEvents: 'none' }}>
      <title>
        {`Work Point (WP) -- implied origin at grid ${workPoint.grid_ref}. ` +
          'Best-guess convention marker (first grid in each axis sequence), not a verified stamped benchmark.'}
      </title>

      {/* Leader line from the label out to the actual grid intersection */}
      <line
        x1={`${ax}%`} y1={`${ay}%`}
        x2={`${cx}%`} y2={`${cy}%`}
        stroke={WP_COLOR}
        strokeWidth={1.6}
        markerEnd="url(#wp-arrowhead)"
      />

      <defs>
        <marker
          id="wp-arrowhead"
          markerWidth="8"
          markerHeight="8"
          refX="6"
          refY="4"
          orient="auto"
        >
          <path d="M0,0 L8,4 L0,8 Z" fill={WP_COLOR} />
        </marker>
      </defs>

      {/* Target crosshair at the actual origin grid intersection -- kept
        deliberately light (thin dashed ring, no solid fill/center dot) since
        a corner grid intersection is very often exactly where a real column
        symbol and its beam/joist callouts are drawn. A bold solid marker
        there would visually fight with that real content instead of just
        pointing it out. */}
      <circle
        cx={`${cx}%`} cy={`${cy}%`} r={4.5}
        fill="none" stroke={WP_COLOR} strokeWidth={1.2}
        strokeDasharray="2,1.5"
        opacity={0.85}
      />

      {/* "WP" label + grid reference, centered on the outside anchor point.
        No background box -- an opaque box here was covering real sheet
        notes/text underneath it (exactly the kind of "disturbing other
        material detail" problem already fixed for the crosshair itself).
        Legibility instead comes from a white halo stroke behind the colored
        fill, the same technique DimensionLine.tsx already uses elsewhere in
        this overlay -- readable over both blank paper and dense linework
        without blocking anything. */}
      <g style={{ paintOrder: 'stroke fill' }}>
        <text
          x={`${ax}%`} y={`${ay - 0.3}%`}
          fill={WP_COLOR}
          fontSize="10px"
          fontWeight="800"
          textAnchor="middle"
          style={{
            userSelect: 'none', letterSpacing: '0.04em',
            stroke: '#FFFFFF', strokeWidth: 3, strokeLinejoin: 'round',
          }}
        >
          WP
        </text>
        <text
          x={`${ax}%`} y={`${ay + 2.3}%`}
          fill={WP_COLOR}
          fontSize="7.5px"
          fontWeight="700"
          textAnchor="middle"
          style={{
            userSelect: 'none',
            stroke: '#FFFFFF', strokeWidth: 2.5, strokeLinejoin: 'round',
          }}
        >
          {workPoint.grid_ref}
        </text>
      </g>
    </g>
  )
}
