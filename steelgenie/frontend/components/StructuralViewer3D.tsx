'use client'

import React, { useEffect, useRef, useState, useCallback } from 'react'
import { modelApi, floorsApi, bomApi } from '../lib/api'
import { useWorkspaceStore } from '../lib/stores/workspaceStore'
import { buildingScene, TYPE_COLOR, UNLABELED_BEAM_COLOR, STATUS_COLOR_FOR_LEGEND } from '../lib/stores/buildingSceneStore'
import type { RawMember, RawGridLine, ColorMode, SceneMember } from '../lib/stores/buildingSceneStore'
import { Spinner } from './ui/Spinner'
import { Box, RefreshCw, PanelRight, ChevronDown, X, AlertTriangle, MousePointer2, Grid3X3, Layers, Search, Ruler, Scissors, Maximize2 } from 'lucide-react'
import { toast } from 'sonner'
import { PropertiesPanel } from '../features/workspace/components/RightSidebar/PropertiesPanel'
import { useMembers } from '../features/workspace/hooks/useMembers'

// ─── Types (kept for Floor / Scope UI) ───────────────────────────────────────

interface FloorPage {
  page_id: string
  idx: number
  title: string | null
  sheet_no: string | null
  zone_label: string | null
  status: string
}

interface Floor {
  id: string
  name: string
  sort_order: number
  status: string
  pages: FloorPage[]
}

type Scope = { kind: 'building' } | { kind: 'floor'; id: string; label: string } | { kind: 'sheet'; id: string; label: string }

// Legend chips when colorMode === 'member_type'. `color` doubles as the
// buildingScene color-group key, so clicking a chip can hide/show exactly
// that group via setColorGroupVisible.
const LEGEND_ITEMS = [
  { label: 'Beams (labeled)',   color: TYPE_COLOR.beam },
  { label: 'Beams (unlabeled)', color: UNLABELED_BEAM_COLOR },
  { label: 'Columns',           color: TYPE_COLOR.column },
  { label: 'Braces',            color: TYPE_COLOR.vbrace },
  { label: 'Joists',            color: TYPE_COLOR.joist },
]

const STATUS_LEGEND_ITEMS = [
  { label: 'Verified',     color: STATUS_COLOR_FOR_LEGEND.verified },
  { label: 'Active',       color: STATUS_COLOR_FOR_LEGEND.active },
  { label: 'Need Review',  color: STATUS_COLOR_FOR_LEGEND.need_review },
  { label: 'Rejected',     color: STATUS_COLOR_FOR_LEGEND.rejected },
  { label: 'Excluded',     color: STATUS_COLOR_FOR_LEGEND.excluded },
]

const COLOR_MODE_OPTIONS: { id: ColorMode; label: string; hasRealData: boolean }[] = [
  { id: 'member_type', label: 'Member Type', hasRealData: true },
  { id: 'status',      label: 'Status',      hasRealData: true },
  { id: 'sequence',    label: 'Sequence',    hasRealData: false },
  { id: 'weight',      label: 'Weight',      hasRealData: true },
  { id: 'labor_code',  label: 'Labor Code',  hasRealData: false },
  { id: 'paint',       label: 'Paint',       hasRealData: false },
]

const SUMMARY_ROWS: Array<[string, string]> = [
  ['column',           'Column'],
  ['beam',             'Beam'],
  ['vertical_brace',   'Vertical Brace'],
  ['horizontal_brace', 'Horizontal Brace'],
  ['joists',           'Joists'],
  ['moment_connection','Moment Connection'],
  ['bolt',             'Bolt'],
  ['embed_plate',      'Embed Plate'],
  ['camber',           'Camber'],
  ['anchor',           'Anchor'],
  ['weld_studs',       'Weld Studs'],
]

function formatFeetInches(ft: number): string {
  const feet = Math.floor(ft)
  const inches = Math.round((ft - feet) * 12)
  if (inches === 12) return `${feet + 1}'-0"`
  return `${feet}'-${inches}"`
}

// ─── Component ────────────────────────────────────────────────────────────────

export default function StructuralViewer3D({
  projectId,
  refreshSignal,
}: {
  projectId: string
  refreshSignal?: number
}) {
  // Three.js canvas host — owned exclusively by the scene store (never share with React children)
  const canvasHostRef = useRef<HTMLDivElement>(null)
  const mountRef      = useRef<HTMLDivElement>(null)

  const { selectedMemberId, selection, toggleSelection, clearSelection } = useWorkspaceStore()

  const [loading,       setLoading]       = useState(true)

  // 3D Build progress/loading states
  const [progress, setProgress] = useState(0)
  const [loadingStage, setLoadingStage] = useState('Connecting to model server...')
  const [showOverlay, setShowOverlay] = useState(false)
  const [overlayOpacity, setOverlayOpacity] = useState(1)
  const [registering,   setRegistering]   = useState(false)
  const [memberCount,   setMemberCount]   = useState(0)
  const [gridCount,     setGridCount]     = useState(0)
  const [floors,        setFloors]        = useState<Floor[]>([])
  const [colorMode,     setColorModeState]= useState<ColorMode>('member_type')
  const [scope,         setScope]         = useState<Scope>({ kind: 'building' })
  // Closed by default — the reference product only shows this once you
  // click the panel-toggle icon in the corner, not automatically.
  const [showSummary,   setShowSummary]   = useState(false)
  const [projectSummary,setProjectSummary]= useState<any>(null)
  const [sheetSummary,  setSheetSummary]  = useState<any>(null)
  const [hoverInfo, setHoverInfo] = useState<{ text: string; x: number; y: number } | null>(null)
  const [showColorMenu, setShowColorMenu] = useState(false)
  const [showScopeMenu, setShowScopeMenu] = useState(false)
  const [showCameraMenu, setShowCameraMenu] = useState(false)
  const [projectSummaryOpen, setProjectSummaryOpen] = useState(true)
  const [sheetSummaryOpen,   setSheetSummaryOpen]   = useState(true)
  // Legend re-renders on hide/show clicks even though hiddenColorKeys lives
  // on the scene store, not React state.
  const [, forceLegendTick] = useState(0)
  const toolbarRef = useRef<HTMLDivElement>(null)
  // Marquee/window-select drag rectangle, in canvas-local pixels.
  const [marqueeRect, setMarqueeRect] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null)
  // Last hovered member, shown in the persistent bottom info bar (matches
  // the reference product's "PIECEMARK | PROFILE | LENGTH | WEIGHT" strip).
  const [statusMember, setStatusMember] = useState<{ piecemark: string | null; profile: string | null; x1: number; z1: number; x2: number; z2: number; weight_lbs: number | null } | null>(null)
  const [projectionMode, setProjectionModeState] = useState<'orthographic' | 'perspective'>('orthographic')
  const [gridVisible, setGridVisibleState] = useState(true)

  // Professional viewer tools: type isolation, opacity/X-ray, search, clip, measure
  const [showToolsMenu, setShowToolsMenu] = useState(false)
  const [typeVisibility, setTypeVisibility] = useState<Record<string, boolean>>({
    column: true, beam: true, vbrace: true, hbrace: true, brace: true, joist: true,
  })
  const [opacity, setOpacity] = useState(1)
  const [clipEnabled, setClipEnabled] = useState(false)
  const [clipY, setClipY] = useState(50)
  const [measureMode, setMeasureModeState] = useState(false)
  const [measureResult, setMeasureResult] = useState<number | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const toolsMenuRef = useRef<HTMLDivElement>(null)

  // Close any flyout on outside click
  useEffect(() => {
    if (!showColorMenu && !showScopeMenu && !showCameraMenu && !showToolsMenu) return
    const onClick = (e: MouseEvent) => {
      const inToolbar = toolbarRef.current && toolbarRef.current.contains(e.target as Node)
      const inTools = toolsMenuRef.current && toolsMenuRef.current.contains(e.target as Node)
      if (!inToolbar && !inTools) {
        setShowColorMenu(false)
        setShowScopeMenu(false)
        setShowCameraMenu(false)
        setShowToolsMenu(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [showColorMenu, showScopeMenu, showCameraMenu, showToolsMenu])

  // Apply clip plane whenever toggled/dragged
  useEffect(() => {
    buildingScene.setClipY(clipEnabled ? clipY : null)
  }, [clipEnabled, clipY])

  // Esc cancels an in-progress measurement
  useEffect(() => {
    if (!measureMode) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setMeasureModeState(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [measureMode])

  // Toggle measure mode on the scene store
  useEffect(() => {
    buildingScene.toggleMeasureMode(measureMode)
    if (!measureMode) setMeasureResult(null)
  }, [measureMode])

  // Re-render when scene store notifies (e.g. member count changes)
  useEffect(() => buildingScene.subscribe(() => {
    setMemberCount(buildingScene.members.size)
    setGridCount(buildingScene.grids.size)
  }), [])

  // showSummary starts closed (matches the reference product's default
  // empty-state), but nothing was ever re-opening it once a member got
  // selected -- so clicking a beam/column in the 3D view selected it (the
  // hover tooltip and 2D highlight both worked) but its properties panel
  // stayed hidden behind a toggle icon the user had no reason to know
  // existed yet. Selecting something is an explicit request to inspect it,
  // so force the dock open the moment a selection appears; it stays
  // user-controlled (via the corner toggle) the rest of the time.
  const prevSelectionSizeRef = useRef(0)
  useEffect(() => {
    if (prevSelectionSizeRef.current === 0 && selection.size > 0) {
      setShowSummary(true)
    }
    prevSelectionSizeRef.current = selection.size
  }, [selection.size])

  // Manage 3D build stages and progress bar animation
  useEffect(() => {
    if (loading) {
      setShowOverlay(true)
      setOverlayOpacity(1)
      setProgress(0)
      setLoadingStage('Connecting to model server...')
      
      const stages = [
        'Connecting to model server...',
        'Fetching member geometry...',
        'Assembling column configurations...',
        'Resolving beam spans and orientations...',
        'Validating vertical & horizontal braces...',
        'Assembling joists and elevations...',
        'Building 3D structural model...',
        'Optimizing spatial index grids...',
        'Finalizing Three.js rendering buffers...'
      ]
      
      let stageIdx = 0
      const stageInterval = setInterval(() => {
        if (stageIdx < stages.length - 1) {
          stageIdx++
          setLoadingStage(stages[stageIdx])
        }
      }, 550)

      const progressInterval = setInterval(() => {
        setProgress((prev) => {
          if (prev >= 95) return 95
          const diff = Math.max(1, Math.floor((98 - prev) * 0.15))
          return prev + diff
        })
      }, 120)

      return () => {
        clearInterval(stageInterval)
        clearInterval(progressInterval)
      }
    } else {
      setProgress(100)
      setLoadingStage('3D model ready!')
      const fadeTimeout = setTimeout(() => {
        setOverlayOpacity(0)
        const hideTimeout = setTimeout(() => {
          setShowOverlay(false)
        }, 300)
        return () => clearTimeout(hideTimeout)
      }, 400)
      return () => clearTimeout(fadeTimeout)
    }
  }, [loading])

  // ── Bootstrap scene on mount ───────────────────────────────────────────────
  useEffect(() => {
    if (!canvasHostRef.current || !projectId) return
    buildingScene.initScene(canvasHostRef.current, projectId)

    // Attach mouse handlers.
    // Left-drag orbits the camera (matches the reference product's free
    // 3D navigation); Shift+drag or right-drag pans instead, since orbiting
    // is now the default gesture. Window/marquee select (drag a rectangle
    // to select every member inside it) uses Ctrl+drag, mirroring the
    // reference's "Window selection" tool tooltip.
    const el = canvasHostRef.current
    let panMode = false
    let marqueeMode = false
    const onDown  = (e: MouseEvent) => {
      buildingScene.isMouseDown = true
      buildingScene.dragged     = false
      buildingScene.prevMouse   = { x: e.clientX, y: e.clientY }
      panMode = e.shiftKey || e.button === 2
      marqueeMode = e.ctrlKey && e.button === 0
      if (marqueeMode && canvasHostRef.current) {
        const rect = canvasHostRef.current.getBoundingClientRect()
        setMarqueeRect({ x0: e.clientX - rect.left, y0: e.clientY - rect.top, x1: e.clientX - rect.left, y1: e.clientY - rect.top })
      }
    }
    const onMove  = (e: MouseEvent) => {
      if (!canvasHostRef.current) return
      const rect = canvasHostRef.current.getBoundingClientRect()
      if (buildingScene.isMouseDown) {
        const ddx = e.clientX - buildingScene.prevMouse.x
        const ddy = e.clientY - buildingScene.prevMouse.y
        if (Math.abs(ddx) > 2 || Math.abs(ddy) > 2) buildingScene.dragged = true
        buildingScene.prevMouse = { x: e.clientX, y: e.clientY }
        if (marqueeMode) {
          setMarqueeRect(r => r && { ...r, x1: e.clientX - rect.left, y1: e.clientY - rect.top })
          return
        }
        if (panMode) {
          buildingScene.panBy(ddx, ddy, rect.width, rect.height)
        } else {
          buildingScene.orbitBy(ddx, ddy)
        }
        return
      }
      // Hover pick
      const wp = buildingScene.screenToWorld(e.clientX, e.clientY, canvasHostRef.current!)
      if (!wp) { setHoverInfo(null); return }
      const tol  = 1.5 / buildingScene.zoom
      const mid  = buildingScene.pickAt(wp.x, wp.z, tol)
      if (mid) {
        const globalId = buildingScene.memberIdToGlobal.get(mid)
        const m        = globalId ? buildingScene.members.get(globalId) : null
        if (m) {
          const statusPart = m.type ? ` | ${m.type}` : ''
          setHoverInfo({ text: `${m.piecemark || mid} | ${m.profile || 'unknown'}${statusPart}`, x: e.clientX, y: e.clientY })
          setStatusMember(m)
          return
        }
      }
      setHoverInfo(null)
    }
    const onUp    = (e: MouseEvent) => {
      buildingScene.isMouseDown = false
      if (marqueeMode && canvasHostRef.current) {
        setMarqueeRect(r => {
          if (r && canvasHostRef.current) {
            const ids = buildingScene.pickInRect(
              Math.min(r.x0, r.x1), Math.min(r.y0, r.y1), Math.max(r.x0, r.x1), Math.max(r.y0, r.y1),
              canvasHostRef.current,
            )
            if (ids.length) {
              const ws = useWorkspaceStore.getState()
              ws.setSelection(new Set(ids))
            }
          }
          return null
        })
        marqueeMode = false
        return
      }
      if (!buildingScene.dragged && canvasHostRef.current && e.button === 0) {
        const wp  = buildingScene.screenToWorld(e.clientX, e.clientY, canvasHostRef.current)
        if (buildingScene.measureMode) {
          if (wp) {
            const dist = buildingScene.addMeasurePoint(wp.x, wp.z)
            if (dist != null) setMeasureResult(dist)
          }
          return
        }
        const tol = 1.5 / buildingScene.zoom
        const mid = wp ? buildingScene.pickAt(wp.x, wp.z, tol) : null
        // Shift-click adds/removes from the multi-selection (mirrors the 2D
        // plan canvas); plain click replaces the selection with just this one.
        if (e.shiftKey && mid) {
          useWorkspaceStore.getState().toggleSelection(mid)
        } else {
          useWorkspaceStore.getState().selectMember(mid)
        }
      }
    }
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const factor = e.deltaY < 0 ? 1.12 : 0.89
      buildingScene.dolly(factor)
    }
    const onContextMenu = (e: MouseEvent) => e.preventDefault()
    const onResize = () => { if (canvasHostRef.current) buildingScene.handleResize(canvasHostRef.current) }

    el.addEventListener('mousedown', onDown)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    el.addEventListener('wheel', onWheel, { passive: false })
    el.addEventListener('contextmenu', onContextMenu)
    window.addEventListener('resize', onResize)

    return () => {
      el.removeEventListener('mousedown', onDown)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      el.removeEventListener('wheel', onWheel)
      el.removeEventListener('contextmenu', onContextMenu)
      window.removeEventListener('resize', onResize)
      // Release the WebGL context on unmount. React remounts this component
      // on a FRESH DOM node every time (dev-mode StrictMode double-invoke,
      // navigating away and back, etc.), and initScene()'s "same container ->
      // reuse" fast path only fires when the container is literally the same
      // element -- a remount never qualifies. Without this, the old
      // WebGLRenderer/canvas from the previous mount was never disposed;
      // it just sat there until the NEXT initScene() call happened to call
      // destroyScene() on its way to creating a new one. Every mount that
      // never got a "next" call (navigate away and don't come back) leaked
      // one live WebGL context permanently. Chrome hard-caps a page at ~16
      // contexts, so after enough navigation this made the 3D view fail
      // outright with "WebGL context could not be created" for the rest of
      // the session. Member DATA (buildingScene.members) is untouched here --
      // only the Three.js renderer/scene/camera get torn down, so the
      // "persistent scene, incremental append" model still holds on remount.
      buildingScene.destroyScene()
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  // ── Selection sync: color swap in scene store ──────────────────────────────
  // Driven off the full `selection` Set, not just `selectedMemberId` -- the
  // 2D plan canvas's click handler only ever updates `selection`
  // (setSelection/toggleSelection), never `selectedMemberId`, so watching
  // selectedMemberId alone meant a 2D click never visibly highlighted
  // anything here even though the properties panel and 2D highlight both
  // worked. See applySelection()'s doc comment for the full story.
  useEffect(() => {
    buildingScene.applySelection(selection)
  }, [selection])

  // Member editing only works when the 3D view is scoped to a single sheet —
  // that's the only scope where the member IDs in the scene match a real,
  // single-page `members` table the existing 2D properties editor can call
  // membersApi against. At building/floor scope, members are merged across
  // multiple pages and don't map 1:1 to editable rows.
  const sheetPageId = scope.kind === 'sheet' ? scope.id : null
  const {
    members: sheetMembers,
    updateMember: sheetUpdateMember,
    deleteMember: sheetDeleteMember,
    bulkUpdateMembers: sheetBulkUpdateMembers,
    bulkDeleteMembers: sheetBulkDeleteMembers,
  } = useMembers(sheetPageId)
  const sheetPageTos = sheetPageId
    ? ((floors.flatMap(f => f.pages) as any[]).find((p: any) => p.page_id === sheetPageId)?.tos_ft ?? null)
    : null

  // ── Color mode: reassign all member color buckets ─────────────────────────
  useEffect(() => {
    buildingScene.setColorMode(colorMode)
  }, [colorMode])

  // ── Data loading ──────────────────────────────────────────────────────────

  const ensureRegistered = useCallback(async (force = false) => {
    try { await floorsApi.registerAll(projectId, force) } catch { /* non-fatal */ }
  }, [projectId])

  const loadFloors = useCallback(async () => {
    try { setFloors(await floorsApi.list(projectId) || []) } catch { setFloors([]) }
  }, [projectId])

  /**
   * Load model data and feed it into the scene store.
   * Uses INCREMENTAL mode: only new pages are appended to the existing scene.
   * Pass force=true to trigger a full rebuild (scope/colorMode change, manual rebuild).
   * Pass forcePageId when a SPECIFIC already-loaded page's members changed
   * (a 2D edit, not a brand-new extraction) -- addPageMembers otherwise
   * no-ops for pages already in pageLoadedSet, which is correct for "skip
   * pages that haven't changed" but wrong for "this exact page WAS just
   * edited and needs its geometry rebuilt," so that one page gets force=true
   * while every other already-loaded page is still left alone (cheap).
   */
  const loadModel = useCallback(async (currentScope: Scope, force = false, forcePageId?: string | null) => {
    setLoading(true)
    try {
      const scopeParam = currentScope.kind
      const scopeId    = currentScope.kind === 'building' ? undefined : currentScope.id
      const data = await modelApi.merged(projectId, scopeParam as any, scopeId)
      const members: RawMember[]  = data.members || []
      const grids:   RawGridLine[] = data.grids   || []

      if (force || buildingScene.pageLoadedSet.size === 0) {
        // Full rebuild — scope changed or first load
        buildingScene.rebuildFull(members, grids)
      } else {
        // Incremental — group by page and append only new (or edited) ones.
        // Columns are excluded from this per-page bucketing and handled by
        // replaceColumns() instead: every column always carries the SAME
        // (foundation-plan-anchored) page_id regardless of which floor
        // extraction most recently grew its height, so routing them through
        // the per-page "already loaded" gate below silently dropped every
        // re-sync after the first floor. See replaceColumns() for the full
        // root-cause writeup.
        const nonColumnMembers = members.filter(m => m.type !== 'column')
        const columnMembers    = members.filter(m => m.type === 'column')

        buildingScene.replaceColumns(columnMembers)

        const byPage = new Map<string, RawMember[]>()
        for (const m of nonColumnMembers) {
          if (!byPage.has(m.page_id)) byPage.set(m.page_id, [])
          byPage.get(m.page_id)!.push(m)
        }
        for (const [pageId, pageMembers] of byPage) {
          buildingScene.addPageMembers(pageId, pageMembers, pageId === forcePageId)
        }
        buildingScene.addPageGrids(grids)
      }
    } catch {
      toast.error('Failed to load 3D model')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  const loadSummaries = useCallback(async (currentScope: Scope) => {
    try { setProjectSummary(await bomApi.modelSummary(projectId)) } catch { setProjectSummary(null) }
    if (currentScope.kind === 'sheet') {
      try { setSheetSummary(await bomApi.modelSummary(projectId, currentScope.id)) } catch { setSheetSummary(null) }
    } else {
      setSheetSummary(null)
    }
  }, [projectId])

  // ── Initial load ──────────────────────────────────────────────────────────

  useEffect(() => {
    if (!projectId) return
    ;(async () => {
      await ensureRegistered()
      await Promise.all([loadFloors(), loadModel(scope), loadSummaries(scope)])
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  // ── refreshSignal: incremental update after new extraction OR a 2D edit ───
  // lastEditedPageId (set by useMembers.ts on every create/update/delete)
  // tells loadModel which already-loaded page needs to be force-rebuilt
  // rather than skipped -- see loadModel's forcePageId doc comment. This is
  // what makes "edit a beam in the 2D plan" actually show up in 3D instead
  // of only new extractions doing so.

  const didMountRef = useRef(false)
  useEffect(() => {
    if (!didMountRef.current) { didMountRef.current = true; return }
    if (refreshSignal === undefined || !projectId) return
    const editedPageId = useWorkspaceStore.getState().lastEditedPageId
    ;(async () => {
      await ensureRegistered(false)
      await Promise.all([loadFloors(), loadModel(scope, false, editedPageId), loadSummaries(scope)])
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshSignal])

  // ── Scope change: full rebuild for that scope ─────────────────────────────

  const prevScopeRef = useRef(scope)
  useEffect(() => {
    if (prevScopeRef.current === scope) return
    prevScopeRef.current = scope
    if (!projectId) return
    loadModel(scope, true)
    loadSummaries(scope)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope])

  // ── Manual Rebuild ────────────────────────────────────────────────────────

  const handleRebuild = async () => {
    setRegistering(true)
    try {
      await ensureRegistered(true)
      await loadFloors()
      await loadModel(scope, true)
      await loadSummaries(scope)
      toast.success('Sheets re-registered and model rebuilt')
    } catch { toast.error('Rebuild failed') }
    finally { setRegistering(false) }
  }

  // ─── JSX ─────────────────────────────────────────────────────────────────

  const containerStyle: React.CSSProperties = {
    position: 'relative', width: '100%', height: '100%',
    backgroundColor: '#F1F5F9', overflow: 'hidden'
  }

  // NOTE: the canvas host below is ALWAYS mounted, even while loading / empty
  // — it used to live behind early `return`s for those states, which meant
  // canvasHostRef.current was null on first paint (loading state renders
  // first), the one-time bootstrap effect saw a null ref and gave up, and
  // buildingScene.initScene() never ran for the rest of the component's
  // life. Result: toolbar/legend/panel all render fine (they don't depend on
  // the scene), but the canvas itself stays permanently blank. Loading and
  // empty states are now overlays on top of the same persistent canvas node
  // instead of separate return branches.
  const hasExtractedPages = floors.some((f: any) =>
    f.pages?.some((p: any) => p.status === 'built' || p.status === 'estimating')
  )
  const showLoadingOverlay = showOverlay
  const showEmptyOverlay   = !showLoadingOverlay && memberCount === 0

  return (
    <div style={containerStyle}>
      {/* Three.js exclusively owns this node */}
      <div ref={mountRef} style={{ position: 'absolute', inset: 0 }}>
        <div ref={canvasHostRef} style={{ position: 'absolute', inset: 0 }} />
      </div>

      {/* Window/marquee selection rectangle (Ctrl+drag) */}
      {marqueeRect && (
        <div style={{
          position: 'absolute', zIndex: 12, pointerEvents: 'none',
          left: Math.min(marqueeRect.x0, marqueeRect.x1),
          top: Math.min(marqueeRect.y0, marqueeRect.y1),
          width: Math.abs(marqueeRect.x1 - marqueeRect.x0),
          height: Math.abs(marqueeRect.y1 - marqueeRect.y0),
          border: '1px solid #3B82F6', backgroundColor: 'rgba(59,130,246,0.12)',
        }} />
      )}

      {showLoadingOverlay && (
        <div style={{
          position: 'absolute',
          inset: 0,
          zIndex: 15,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundColor: memberCount === 0 ? '#0F172A' : 'rgba(15, 23, 42, 0.78)',
          backdropFilter: memberCount === 0 ? 'none' : 'blur(8px)',
          transition: 'opacity 0.3s ease',
          opacity: overlayOpacity,
          color: '#fff',
          fontFamily: 'Inter, sans-serif',
          pointerEvents: overlayOpacity === 0 ? 'none' : 'all'
        }}>
          {/* Stunning 3D Cube Loader in CSS */}
          <div className="cube-wrapper">
            <div className="cube">
              <div className="face front"></div>
              <div className="face back"></div>
              <div className="face right"></div>
              <div className="face left"></div>
              <div className="face top"></div>
              <div className="face bottom"></div>
            </div>
          </div>

          <h2 style={{ margin: '0 0 10px 0', fontSize: '18px', fontWeight: 700, letterSpacing: '-0.02em', background: 'linear-gradient(to right, #F1F5F9, #94A3B8)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
            {progress === 100 ? 'Model Ready' : 'Assembling 3D Model'}
          </h2>

          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '10px' }}>
            <div style={{
              width: '240px',
              height: '6px',
              backgroundColor: 'rgba(255, 255, 255, 0.08)',
              borderRadius: '999px',
              overflow: 'hidden',
              border: '1px solid rgba(255, 255, 255, 0.05)',
              position: 'relative'
            }}>
              <div style={{
                width: `${progress}%`,
                height: '100%',
                background: 'linear-gradient(to right, #6366F1, #06B6D4)',
                borderRadius: '999px',
                transition: progress === 0 ? 'none' : 'width 0.25s cubic-bezier(0.4, 0, 0.2, 1)',
                boxShadow: '0 0 8px rgba(99, 102, 241, 0.5)'
              }} />
            </div>
            <span style={{ fontSize: '12px', fontWeight: 700, color: '#38BDF8', width: '32px', textAlign: 'right' }}>
              {progress}%
            </span>
          </div>

          <span style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', height: '16px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            {progress < 100 && <span className="pulse-dot" />}
            {loadingStage}
          </span>

          <style>{`
            .cube-wrapper {
              perspective: 800px;
              width: 50px;
              height: 50px;
              margin-bottom: 28px;
            }
            .cube {
              width: 100%;
              height: 100%;
              position: relative;
              transform-style: preserve-3d;
              animation: rotateCube 3.5s infinite ease-in-out;
            }
            .face {
              position: absolute;
              width: 100%;
              height: 100%;
              border: 1.5px solid #06B6D4;
              background: rgba(6, 182, 212, 0.05);
              box-shadow: inset 0 0 6px rgba(6, 182, 212, 0.2);
            }
            .front  { transform: rotateY(  0deg) translateZ(25px); }
            .back   { transform: rotateY(180deg) translateZ(25px); }
            .right  { transform: rotateY( 90deg) translateZ(25px); }
            .left   { transform: rotateY(-90deg) translateZ(25px); }
            .top    { transform: rotateX( 90deg) translateZ(25px); }
            .bottom { transform: rotateX(-90deg) translateZ(25px); }

            @keyframes rotateCube {
              0% { transform: rotateX(0deg) rotateY(0deg); }
              30% { transform: rotateX(180deg) rotateY(90deg); }
              65% { transform: rotateX(90deg) rotateY(270deg); }
              100% { transform: rotateX(360deg) rotateY(360deg); }
            }

            .pulse-dot {
              width: 6px;
              height: 6px;
              border-radius: 50%;
              background-color: #38BDF8;
              box-shadow: 0 0 8px #38BDF8;
              animation: pulse 1.2s infinite alternate;
            }

            @keyframes pulse {
              0% { opacity: 0.3; transform: scale(0.8); }
              100% { opacity: 1; transform: scale(1.2); }
            }
          `}</style>
        </div>
      )}

      {showEmptyOverlay && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 15, backgroundColor: '#F1F5F9', display: 'flex', flexDirection: 'column', padding: '24px' }}>
          <div style={{ marginBottom: '20px' }}>
            <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#111827' }}>3D Structural Model</h1>
            <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>Whole-building model assembled from all extracted pages</p>
          </div>
          <div style={{
            flex: 1, border: '1px dashed rgba(59,130,246,0.3)', borderRadius: '12px',
            backgroundColor: 'rgba(30,41,59,0.05)', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: '12px', padding: '40px', textAlign: 'center',
          }}>
            <Box size={40} style={{ color: hasExtractedPages ? '#F59E0B' : '#3B82F6' }} />
            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: '#334155' }}>
              {hasExtractedPages ? 'Missing Top of Steel (T.O.S.)' : 'Extract a drawing to view the model'}
            </h3>
            <p style={{ margin: 0, fontSize: '13px', color: '#475569', maxWidth: '420px', lineHeight: 1.5 }}>
              {hasExtractedPages
                ? 'You have extracted pages, but they cannot be placed in the 3D model until they have a valid Top of Steel elevation. Please set the T.O.S. for your pages in the left sidebar.'
                : 'Once at least one page has been extracted or built, its beams, joists, and braces are assembled into this 3D view along with the real extracted grid lines. Sheets belonging to the same floor (matched by Top of Steel) are automatically merged into one contiguous floor plan.'
              }
            </p>
          </div>
        </div>
      )}

      {/* Toolbar / legend / properties only make sense once there's a model */}
      {!showLoadingOverlay && !showEmptyOverlay && <>

      {/* Floating Toolbar (Top Right) */}
      <div ref={toolbarRef} style={{ 
        position: 'absolute', top: 16, right: showSummary ? 300 : 56, zIndex: 10,
        display: 'flex', alignItems: 'center', gap: '8px',
        backgroundColor: '#111827', padding: '6px', borderRadius: '8px',
        border: '1px solid rgba(255,255,255,0.08)', boxShadow: '0 4px 12px rgba(0,0,0,0.2)'
      }}>
        {/* Select tool -- click a member to select it, Shift+click to add to
            the selection, Ctrl+drag for a window/marquee selection (only
            members fully inside the rectangle get selected). */}
        <button
          title="Window selection: drag a rectangle to select members fully inside it (shortcut: hold Ctrl + drag)"
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', width: '32px', height: '32px',
            borderRadius: '6px', border: 'none', backgroundColor: '#3B82F6', color: '#fff', cursor: 'pointer'
          }}
        >
          <MousePointer2 size={16} />
        </button>

        {/* Grid axes toggle */}
        <button
          title="Show grid axes"
          onClick={() => {
            const next = !gridVisible
            setGridVisibleState(next)
            buildingScene.setGridVisible(next)
          }}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', width: '32px', height: '32px',
            borderRadius: '6px', border: 'none', cursor: 'pointer',
            backgroundColor: gridVisible ? '#1E293B' : 'transparent',
            color: gridVisible ? '#fff' : '#64748B',
          }}
        >
          <Grid3X3 size={16} />
        </button>

        {/* Camera views: Perspective/Orthographic + Top/Front/Back/Left/Right/Home/Iso presets */}
        <div style={{ position: 'relative' }}>
          <button
            title="Camera views"
            onClick={() => setShowCameraMenu(v => !v)}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', width: '32px', height: '32px',
              borderRadius: '6px', border: 'none', cursor: 'pointer',
              backgroundColor: showCameraMenu ? '#1E293B' : 'transparent',
              color: showCameraMenu ? '#fff' : '#94A3B8',
            }}
          >
            <Box size={16} />
          </button>
          {showCameraMenu && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, marginTop: '8px', width: '160px', zIndex: 50,
              backgroundColor: '#102030', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px',
              boxShadow: '0 8px 24px rgba(0,0,0,0.4)', padding: '10px',
            }}>
              <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '6px' }}>
                Projection
              </div>
              <div style={{ display: 'flex', backgroundColor: '#0B1220', borderRadius: '6px', padding: '2px', marginBottom: '10px' }}>
                {(['perspective', 'orthographic'] as const).map(mode => (
                  <button
                    key={mode}
                    onClick={() => { setProjectionModeState(mode); buildingScene.setProjectionMode(mode) }}
                    style={{
                      flex: 1, padding: '5px 0', borderRadius: '4px', border: 'none', cursor: 'pointer',
                      fontSize: '10px', fontWeight: 700, textTransform: 'capitalize',
                      backgroundColor: projectionMode === mode ? '#3B82F6' : 'transparent',
                      color: projectionMode === mode ? '#fff' : '#94A3B8',
                    }}
                  >
                    {mode === 'perspective' ? 'Persp.' : 'Ortho'}
                  </button>
                ))}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '4px' }}>
                {([
                  ['nw_iso', 'NW Iso'], ['top', 'Top'], ['ne_iso', 'NE Iso'],
                  ['left', 'Left'], ['home', 'Home'], ['right', 'Right'],
                  ['front', 'Front'], ['back', 'Back'],
                ] as const).map(([id, label]) => (
                  <button
                    key={id}
                    title={label}
                    onClick={() => { buildingScene.setCameraPreset(id); setShowCameraMenu(false) }}
                    style={{
                      display: 'flex', alignItems: 'center', justifyContent: 'center', height: '30px',
                      borderRadius: '5px', border: '1px solid rgba(255,255,255,0.06)', cursor: 'pointer',
                      backgroundColor: '#1E293B', color: '#CBD5E1', fontSize: '9px', fontWeight: 700,
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Fit to selection / fit building */}
        <button
          title={selection.size > 0 ? 'Fit selected member(s)' : 'Fit whole building'}
          onClick={() => {
            if (selection.size > 0) buildingScene.fitToMembers([...selection])
            else buildingScene.fitToBuilding()
          }}
          style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center', width: '32px', height: '32px',
            borderRadius: '6px', border: 'none', cursor: 'pointer', backgroundColor: 'transparent', color: '#94A3B8',
          }}
        >
          <Maximize2 size={16} />
        </button>

        {/* Professional viewer tools: layer isolation, opacity, clip, measure, search */}
        <div style={{ position: 'relative' }} ref={toolsMenuRef}>
          <button
            title="Viewer tools"
            onClick={() => setShowToolsMenu(v => !v)}
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', width: '32px', height: '32px',
              borderRadius: '6px', border: 'none', cursor: 'pointer',
              backgroundColor: showToolsMenu ? '#1E293B' : 'transparent',
              color: showToolsMenu ? '#fff' : '#94A3B8',
            }}
          >
            <Layers size={16} />
          </button>
          {showToolsMenu && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, marginTop: '8px', width: '240px', zIndex: 50,
              backgroundColor: '#102030', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px',
              boxShadow: '0 8px 24px rgba(0,0,0,0.4)', padding: '12px', display: 'flex', flexDirection: 'column', gap: '12px',
            }}>
              {/* Search */}
              <div>
                <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '6px' }}>
                  Find Member
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: '#0B1220', borderRadius: '6px', padding: '6px 8px' }}>
                  <Search size={13} color="#64748B" />
                  <input
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key !== 'Enter') return
                      const q = searchQuery.trim().toLowerCase()
                      if (!q) return
                      const hit = [...buildingScene.members.values()].find(m =>
                        (m.piecemark || '').toLowerCase().includes(q) || m.memberIds.some(id => id.toLowerCase().includes(q))
                      )
                      if (hit) {
                        useWorkspaceStore.getState().selectMember(hit.memberIds[0])
                        buildingScene.fitToMembers([hit.memberIds[0]])
                      } else {
                        toast.error(`No member found matching "${searchQuery}"`)
                      }
                    }}
                    placeholder="Piecemark, e.g. B_2087"
                    style={{ flex: 1, background: 'none', border: 'none', outline: 'none', color: '#F1F5F9', fontSize: '12px' }}
                  />
                </div>
              </div>

              {/* Type isolation */}
              <div>
                <div style={{ fontSize: '10px', fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '6px' }}>
                  Show / Hide
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {([['column', 'Columns'], ['beam', 'Beams'], ['vbrace', 'Braces'], ['joist', 'Joists']] as const).map(([kind, label]) => (
                    <label key={kind} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#CBD5E1', cursor: 'pointer' }}>
                      <input
                        type="checkbox"
                        checked={typeVisibility[kind] !== false}
                        onChange={(e) => {
                          const visible = e.target.checked
                          setTypeVisibility(v => ({ ...v, [kind]: visible }))
                          buildingScene.setTypeVisible(kind, visible)
                          if (kind === 'vbrace') { buildingScene.setTypeVisible('hbrace', visible); buildingScene.setTypeVisible('brace', visible) }
                        }}
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </div>

              {/* Opacity / X-ray */}
              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.04em', marginBottom: '6px' }}>
                  <span>Opacity</span>
                  <span>{Math.round(opacity * 100)}%</span>
                </div>
                <input
                  type="range" min={0.15} max={1} step={0.05} value={opacity}
                  onChange={(e) => { const v = parseFloat(e.target.value); setOpacity(v); buildingScene.setGlobalOpacity(v) }}
                  style={{ width: '100%' }}
                />
              </div>

              {/* Section / clip plane */}
              <div>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: '#CBD5E1', cursor: 'pointer', marginBottom: '6px' }}>
                  <input type="checkbox" checked={clipEnabled} onChange={(e) => setClipEnabled(e.target.checked)} />
                  <Scissors size={13} /> Section cut (elevation ft)
                </label>
                {clipEnabled && (
                  <input
                    type="range" min={-10} max={200} step={1} value={clipY}
                    onChange={(e) => setClipY(parseFloat(e.target.value))}
                    style={{ width: '100%' }}
                  />
                )}
              </div>

              {/* Measure */}
              <button
                onClick={() => setMeasureModeState(v => !v)}
                style={{
                  display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 10px', borderRadius: '6px',
                  border: 'none', cursor: 'pointer', fontSize: '12px', fontWeight: 600,
                  backgroundColor: measureMode ? '#3B82F6' : '#1E293B',
                  color: measureMode ? '#fff' : '#CBD5E1',
                }}
              >
                <Ruler size={14} />
                {measureMode ? 'Click two points… (Esc to cancel)' : 'Measure distance'}
              </button>
              {measureResult != null && (
                <div style={{ fontSize: '12px', color: '#38BDF8', fontWeight: 700 }}>
                  {formatFeetInches(measureResult)}
                </div>
              )}
            </div>
          )}
        </div>

        <div style={{ width: '1px', height: '24px', backgroundColor: 'rgba(255,255,255,0.1)' }} />

        {/* Scope selector */}
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setShowScopeMenu(v => !v)}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '0 10px', height: '32px', borderRadius: '6px',
              border: 'none', cursor: 'pointer', fontSize: '12px', fontWeight: 600,
              backgroundColor: showScopeMenu ? '#1E293B' : 'transparent',
              color: showScopeMenu ? '#fff' : '#E2E8F0', maxWidth: '180px',
            }}
          >
            <span style={{ color: '#E2E8F0' }}>Building</span>
            <ChevronDown size={13} style={{ flexShrink: 0, marginLeft: 2 }} />
          </button>
          {showScopeMenu && (
            <div style={{
              position: 'absolute', top: '100%', right: 0, marginTop: '8px', width: '240px', maxHeight: '360px',
              overflowY: 'auto', zIndex: 50, backgroundColor: '#102030', border: '1px solid rgba(255,255,255,0.08)',
              borderRadius: '8px', boxShadow: '0 8px 24px rgba(0,0,0,0.4)', padding: '4px',
            }}>
              <button
                onClick={() => { setScope({ kind: 'building' }); setShowScopeMenu(false) }}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', padding: '7px 10px', borderRadius: '6px',
                  border: 'none', backgroundColor: scope.kind === 'building' ? '#3B82F6' : 'transparent',
                  color: scope.kind === 'building' ? '#fff' : '#CBD5E1', fontSize: '12px', fontWeight: 700, cursor: 'pointer',
                }}
              >
                Building
              </button>
              {floors.map(f => (
                <div key={f.id} style={{ marginTop: '6px' }}>
                  <div style={{ padding: '4px 10px', fontSize: '10px', fontWeight: 700, color: '#64748B', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
                    {f.name}
                  </div>
                  <button
                    onClick={() => { setScope({ kind: 'floor', id: f.id, label: `${f.name} (whole floor)` }); setShowScopeMenu(false) }}
                    style={{
                      display: 'block', width: '100%', textAlign: 'left', padding: '7px 10px', borderRadius: '6px',
                      border: 'none', backgroundColor: scope.kind === 'floor' && scope.id === f.id ? '#3B82F6' : 'transparent',
                      color: scope.kind === 'floor' && scope.id === f.id ? '#fff' : '#CBD5E1', fontSize: '12px', fontWeight: 600, cursor: 'pointer',
                    }}
                  >
                    {f.name} (whole floor)
                  </button>
                  {f.pages.map(p => {
                    const label = p.title || p.sheet_no || `Page ${p.idx + 1}`
                    const active = scope.kind === 'sheet' && scope.id === p.page_id
                    return (
                      <button
                        key={p.page_id}
                        onClick={() => { setScope({ kind: 'sheet', id: p.page_id, label }); setShowScopeMenu(false) }}
                        style={{
                          display: 'flex', alignItems: 'center', gap: '4px', width: '100%', textAlign: 'left',
                          padding: '7px 10px 7px 20px', borderRadius: '6px', border: 'none',
                          backgroundColor: active ? '#3B82F6' : 'transparent',
                          color: active ? '#fff' : '#94A3B8', fontSize: '12px', fontWeight: 500, cursor: 'pointer',
                          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                        }}
                      >
                        <span style={{ flexShrink: 0, opacity: 0.6 }}>↳</span>
                        {label}{p.zone_label ? ` — ${p.zone_label}` : ''}
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ width: '1px', height: '24px', backgroundColor: 'rgba(255,255,255,0.1)' }} />

        {/* Color-by mode */}
        <div style={{ position: 'relative' }}>
          <button
            onClick={() => setShowColorMenu(v => !v)}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '0 10px', height: '32px', borderRadius: '6px',
              border: 'none', cursor: 'pointer', fontSize: '12px', fontWeight: 600,
              backgroundColor: showColorMenu ? '#1E293B' : 'transparent',
              color: showColorMenu ? '#fff' : '#E2E8F0',
            }}
          >
            <span style={{ color: '#E2E8F0' }}>Member Type</span>
            <ChevronDown size={13} style={{ flexShrink: 0, marginLeft: 2 }} />
          </button>
          {showColorMenu && (
            <div style={{
              position: 'absolute', top: '100%', right: 0, marginTop: '8px', width: '160px', zIndex: 50,
              backgroundColor: '#102030', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '8px',
              boxShadow: '0 8px 24px rgba(0,0,0,0.4)', padding: '4px', display: 'flex', flexDirection: 'column',
            }}>
              {COLOR_MODE_OPTIONS.map(opt => (
                <button
                  key={opt.id}
                  onClick={() => {
                    setColorModeState(opt.id)
                    setShowColorMenu(false)
                    if (!opt.hasRealData) {
                      toast.info(`${opt.label} isn't tracked yet — every member will show as "no data" gray until that's implemented.`)
                    }
                  }}
                  style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between', textAlign: 'left',
                    padding: '7px 10px', borderRadius: '6px', border: 'none',
                    backgroundColor: colorMode === opt.id ? '#3B82F6' : 'transparent',
                    color: colorMode === opt.id ? '#fff' : (opt.hasRealData ? '#CBD5E1' : '#64748B'),
                    fontSize: '12px', fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  {opt.label}
                  {!opt.hasRealData && <span style={{ fontSize: '9px', opacity: 0.8 }}>N/A</span>}
                </button>
              ))}
            </div>
          )}
        </div>

        {floors.some(f => f.status === 'need_review') && (
          <button
            onClick={handleRebuild}
            title="One or more floors couldn't be registered with high confidence"
            style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center', width: '32px', height: '32px',
              borderRadius: '6px', border: 'none', backgroundColor: 'rgba(245,158,11,0.12)', color: '#F59E0B',
              cursor: 'pointer', marginLeft: '4px'
            }}
          >
            <AlertTriangle size={16} />
          </button>
        )}
      </div>

      {/* Floating Panel Toggle */}
      <button
        onClick={() => setShowSummary(s => !s)}
        title="Toggle summary panel"
        style={{
          position: 'absolute', top: 16, right: 16, zIndex: 10,
          display: 'flex', alignItems: 'center', justifyContent: 'center', width: '32px', height: '32px',
          borderRadius: '8px', border: '1px solid rgba(255,255,255,0.08)',
          backgroundColor: '#111827', color: showSummary ? '#3B82F6' : '#94A3B8',
          boxShadow: '0 4px 12px rgba(0,0,0,0.2)', cursor: 'pointer',
        }}
      >
        <PanelRight size={16} />
      </button>

      {/* Properties dock — swaps to the real per-member editor (same one the
          2D plan view uses) as soon as something is selected, exactly like
          the reference: click/shift-click members here to edit them. */}
      {showSummary && selection.size > 0 && scope.kind === 'sheet' && (
        <div style={{
          position: 'absolute', top: 56, right: 16, bottom: 16, zIndex: 10,
          width: '320px', borderRadius: '12px', overflow: 'hidden',
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)', border: '1px solid rgba(255,255,255,0.08)',
        }}>
          <PropertiesPanel
            selection={selection}
            members={sheetMembers}
            onUpdate={async (id, data) => {
              try { await sheetUpdateMember({ id, data }); toast.success('Member properties saved') }
              catch { toast.error('Failed to update member properties') }
            }}
            onDelete={async (id) => {
              try { await sheetDeleteMember(id); toast.success('Member deleted') }
              catch { toast.error('Failed to delete member') }
            }}
            onBulkUpdate={async (ids, update) => {
              try { await sheetBulkUpdateMembers({ ids, update }); toast.success('Selected members updated successfully') }
              catch { toast.error('Failed to update members in bulk') }
            }}
            onBulkDelete={async (ids) => {
              try { await sheetBulkDeleteMembers(ids); toast.success('Selected members deleted successfully'); clearSelection() }
              catch { toast.error('Failed to delete members in bulk') }
            }}
            onClose={clearSelection}
            pageTos={sheetPageTos}
          />
        </div>
      )}

      {/* Selected members, but scope isn't a single sheet — merged
          building/floor members don't map 1:1 to an editable page row, so
          full editing stays sheet-scope-only. That doesn't mean the user
          should see nothing: SceneMember already carries every real
          property (piecemark, profile, length, status, weight, labor
          code, floor) merged from the backend model, so show it read-only
          here instead of a bare "switch scope" placeholder. */}
      {showSummary && selection.size > 0 && scope.kind !== 'sheet' && (() => {
        const rows = [...selection]
          .map(mid => {
            const globalId = buildingScene.memberIdToGlobal.get(mid)
            const m = globalId ? buildingScene.members.get(globalId) : null
            return m ? { mid, m } : null
          })
          .filter((r): r is { mid: string; m: SceneMember } => r !== null)
        return (
        <div style={{
          position: 'absolute', top: 56, right: 16, bottom: 16, zIndex: 10,
          width: '300px', backgroundColor: '#111827',
          border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px',
          overflow: 'hidden', display: 'flex', flexDirection: 'column', fontSize: '12px',
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)',
        }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 14px', borderBottom: '1px solid rgba(255,255,255,0.08)', flexShrink: 0,
          }}>
            <span style={{ fontSize: '13px', fontWeight: 700, color: '#F1F5F9' }}>
              {rows.length} member{rows.length === 1 ? '' : 's'} selected
            </span>
            <button onClick={clearSelection} style={{ background: 'none', border: 'none', color: '#64748B', cursor: 'pointer', padding: '2px', display: 'flex' }}>
              <X size={15} />
            </button>
          </div>
          <div style={{ overflowY: 'auto', flex: 1, padding: '10px 14px 14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {rows.length === 0 && (
              <p style={{ margin: 0, color: '#64748B' }}>No property data loaded for this selection yet.</p>
            )}
            {rows.map(({ mid, m }) => {
              const lengthFt = Math.sqrt(
                (m.x2 - m.x1) ** 2 + (m.y2 - m.y1) ** 2 + (m.z2 - m.z1) ** 2
              )
              const fields: [string, string][] = [
                ['Piecemark', m.piecemark || '—'],
                ['Type', m.type ? m.type.charAt(0).toUpperCase() + m.type.slice(1) : '—'],
                ['Profile', m.profile || 'Unclassified'],
                ['Length', formatFeetInches(lengthFt)],
                ['Elevation (T.O.S.)', `${m.elevation.toFixed(2)} ft`],
                ['Floor', m.floorName || '—'],
                ['Status', m.status || '—'],
                ['Weight', m.weight_lbs != null ? `${m.weight_lbs.toFixed(0)} lbs` : '—'],
                ['Labor code', m.labor_code || '—'],
              ]
              return (
                <div key={mid} style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', paddingBottom: '10px' }}>
                  <div style={{ fontSize: '12px', fontWeight: 700, color: '#F1F5F9', marginBottom: '6px' }}>
                    {m.piecemark || mid}
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', rowGap: '4px', columnGap: '10px' }}>
                    {fields.map(([label, value]) => (
                      <React.Fragment key={label}>
                        <span style={{ color: '#64748B' }}>{label}</span>
                        <span style={{ color: '#CBD5E1', textAlign: 'right' }}>{value}</span>
                      </React.Fragment>
                    ))}
                  </div>
                </div>
              )
            })}
            <p style={{ margin: 0, fontSize: '11px', color: '#64748B', lineHeight: 1.5 }}>
              Read-only here. Switch the <b>Building ▾</b> dropdown above to a single sheet to edit these members.
            </p>
          </div>
        </div>
        )
      })()}

      {/* Summary Panel — shown whenever nothing is selected */}
      {showSummary && selection.size === 0 && (
        <div style={{
          position: 'absolute', top: 56, right: 16, bottom: 16, zIndex: 10,
          width: '270px', backgroundColor: '#111827',
          border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px',
          overflow: 'hidden', display: 'flex', flexDirection: 'column', fontSize: '12px',
          boxShadow: '0 8px 24px rgba(0,0,0,0.3)'
        }}>
          {/* Header */}
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            padding: '12px 14px', borderBottom: '1px solid rgba(255,255,255,0.08)',
          }}>
            <span style={{ fontSize: '13px', fontWeight: 700, color: '#F1F5F9' }}>Properties</span>
            <button
              onClick={() => setShowSummary(false)}
              style={{ background: 'none', border: 'none', color: '#64748B', cursor: 'pointer', padding: '2px', display: 'flex' }}
            >
              <X size={15} />
            </button>
          </div>

          {/* Tab */}
          <div style={{ padding: '10px 14px 0' }}>
            <span style={{
              display: 'inline-block', padding: '5px 12px', borderRadius: '6px',
              backgroundColor: '#1E293B', color: '#3B82F6', fontSize: '11px', fontWeight: 700,
              border: '1px solid rgba(59,130,246,0.3)',
            }}>
              Summary
            </span>
          </div>

          <div style={{ overflowY: 'auto', padding: '10px 14px 14px', flex: 1 }}>
            <CollapsibleSection title="Project Summary" open={projectSummaryOpen} onToggle={() => setProjectSummaryOpen(v => !v)}>
              <SummaryBlock data={projectSummary} />
            </CollapsibleSection>
            <div style={{ height: '12px' }} />
            <CollapsibleSection title="Sheet Summary" open={sheetSummaryOpen} onToggle={() => setSheetSummaryOpen(v => !v)}>
              <SummaryBlock
                data={sheetSummary}
                placeholder={scope.kind === 'sheet' ? undefined : 'Select a sheet from the dropdown above to see its summary'}
              />
            </CollapsibleSection>
          </div>
        </div>
      )}

      {/* Legend — horizontally laid out with circles */}
      {(colorMode === 'member_type' || colorMode === 'status') && (
        <div style={{
          position: 'absolute', bottom: '24px', left: '24px', backgroundColor: '#334155',
          borderRadius: '24px', padding: '8px 16px',
          display: 'flex', alignItems: 'center', gap: '16px', zIndex: 10,
          boxShadow: '0 4px 16px rgba(0,0,0,0.15)',
        }}>
          {(colorMode === 'member_type' ? LEGEND_ITEMS : STATUS_LEGEND_ITEMS).map(item => {
            const hidden = buildingScene.hiddenColorKeys.has(item.color)
            return (
              <button
                key={item.label}
                onClick={() => {
                  buildingScene.setColorGroupVisible(item.color, hidden)
                  forceLegendTick(t => t + 1)
                }}
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px', fontSize: '12px', fontWeight: 600,
                  color: hidden ? '#94A3B8' : '#F1F5F9', background: 'none', border: 'none',
                  padding: '2px 0', cursor: 'pointer', textDecoration: hidden ? 'line-through' : 'none',
                  opacity: hidden ? 0.6 : 1,
                }}
              >
                <span style={{ width: '10px', height: '10px', borderRadius: '50%', backgroundColor: item.color, display: 'inline-block', flexShrink: 0 }} />
                {item.label}
              </button>
            )
          })}
        </div>
      )}

      {/* Persistent bottom-left status strip for the last hovered/selected
          member -- piecemark | profile | length | weight, matching the
          reference product's always-visible info bar (as opposed to a
          tooltip that disappears the instant the mouse leaves). */}
      {statusMember && (
        <div style={{
          position: 'absolute', bottom: '24px', left: (colorMode === 'member_type' || colorMode === 'status') ? '260px' : '24px',
          backgroundColor: 'rgba(15,23,42,0.85)', border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: '6px', padding: '6px 12px', fontSize: '11px', color: '#F1F5F9',
          zIndex: 10, whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: '8px',
        }}>
          <span style={{ fontWeight: 700 }}>{statusMember.piecemark || 'Unlabeled'}</span>
          <span style={{ color: '#475569' }}>|</span>
          <span>{statusMember.profile || 'unknown'}</span>
          <span style={{ color: '#475569' }}>|</span>
          <span>{formatFeetInches(Math.hypot(statusMember.x2 - statusMember.x1, statusMember.z2 - statusMember.z1))}</span>
          <span style={{ color: '#475569' }}>|</span>
          <span>{statusMember.weight_lbs != null ? `${Math.round(statusMember.weight_lbs).toLocaleString()} lb` : '—'}</span>
        </div>
      )}

      {/* Hover tooltip */}
      {hoverInfo && (
        <div style={{
          position: 'fixed', left: hoverInfo.x + 14, top: hoverInfo.y + 14,
          backgroundColor: 'rgba(15,23,42,0.92)', border: '1px solid rgba(255,255,255,0.08)',
          borderRadius: '6px', padding: '6px 10px', fontSize: '11px', color: '#F1F5F9',
          pointerEvents: 'none', zIndex: 20, whiteSpace: 'nowrap',
        }}>
          {hoverInfo.text}
        </div>
      )}
      </>}
    </div>
  )
}


// ─── Collapsible section wrapper ────────────────────────────────────────────

function CollapsibleSection({
  title, open, onToggle, children,
}: { title: string; open: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <div style={{ border: '1px solid rgba(59,130,246,0.12)', borderRadius: '8px', overflow: 'hidden' }}>
      <button
        onClick={onToggle}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '9px 10px', backgroundColor: '#1E293B', border: 'none', cursor: 'pointer',
        }}
      >
        <span style={{ fontSize: '11px', fontWeight: 700, color: '#F1F5F9', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          {title}
        </span>
        <ChevronDown size={13} color="#64748B" style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }} />
      </button>
      {open && <div style={{ padding: '10px' }}>{children}</div>}
    </div>
  )
}

// ─── Summary block ────────────────────────────────────────────────────────────

function SummaryBlock({ data, placeholder }: { data: any; placeholder?: string }) {
  return (
    <div>
      {placeholder ? (
        <p style={{ margin: 0, fontSize: '11px', color: '#475569', lineHeight: 1.5 }}>{placeholder}</p>
      ) : !data ? (
        <p style={{ margin: 0, fontSize: '11px', color: '#475569' }}>Loading…</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
          {SUMMARY_ROWS.map(([key, label]) => (
            <div key={key} style={{ display: 'flex', justifyContent: 'space-between', color: '#CBD5E1' }}>
              <span style={{ color: '#94A3B8' }}>{label}</span>
              <span style={{ fontWeight: 600 }}>{data[key] ?? 0}</span>
            </div>
          ))}
          <div style={{ height: '1px', backgroundColor: 'rgba(59,130,246,0.12)', margin: '4px 0' }} />
          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#CBD5E1' }}>
            <span style={{ color: '#94A3B8' }}>Total Weight (tons)</span>
            <span style={{ fontWeight: 600 }}>{data.total_weight_tons ?? 0}</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', color: '#CBD5E1' }}>
            <span style={{ color: '#94A3B8' }}>Hrs/Ton</span>
            <span style={{ fontWeight: 600 }}>{data.hrs_per_ton ?? 'WIP'}</span>
          </div>
        </div>
      )}
    </div>
  )
}
