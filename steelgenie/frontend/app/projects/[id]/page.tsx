'use client'

import React, { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { Columns } from 'lucide-react'
import { useWorkspaceStore } from '../../../lib/stores/workspaceStore'
import { useWorkspace } from '../../../features/workspace/hooks/useWorkspace'
import { useMembers } from '../../../features/workspace/hooks/useMembers'
import { PageRail } from '../../../features/workspace/components/PageRail/PageRail'
import { CanvasToolbar } from '../../../features/workspace/components/CanvasToolbar'
import { PlanCanvas } from '../../../features/workspace/components/PlanCanvas/PlanCanvas'
import { MembersTab } from '../../../features/workspace/components/LeftSidebar/MembersTab'
import { NavigationPanel } from '../../../features/workspace/components/LeftSidebar/NavigationPanel'
import { PropertiesPanel } from '../../../features/workspace/components/RightSidebar/PropertiesPanel'
import { ScaleCalibrationModal } from '../../../features/workspace/components/ScaleCalibrationModal'
import { SheetSummary } from '../../../features/workspace/components/SheetSummary'
import { VerticalToolStrip } from '../../../features/workspace/components/VerticalToolStrip'
import { KeyPlanView } from '../../../features/workspace/components/KeyPlan/KeyPlanView'
import { KeyPlanPropertiesPanel } from '../../../features/workspace/components/KeyPlan/KeyPlanPropertiesPanel'
import { KeyPlanFloor } from '../../../features/workspace/components/KeyPlan/KeyPlanTypes'
import { supabase } from '../../../lib/supabase'
import { getEventsWebSocketUrl, jobsApi, membersApi, layerPresetsApi, floorsApi, bomApi } from '../../../lib/api'
import { toast } from 'sonner'
import { useQuery, useQueryClient } from '@tanstack/react-query'

export default function TakeoffWorkspacePage() {
  const params = useParams()
  const projectId = params?.id as string

  // Query: Get drawings and pages
  const { drawings, pages, isLoading: workspaceLoading, updatePage } = useWorkspace(projectId)

  const {
    currentPageId,
    currentPageIndex,
    setCurrentPage,
    setScale,
    selectedScale,
    selectedRatio,
    selectedMemberId,
    selectMember,
    selection,
    clearSelection,
    setSelection,
    toggleSelection,
    show3d,
    pushHistoryLog,
    markPageDirty,
    clearPageDirty,
    dirtyPageIds,
    bumpModelRefresh,
  } = useWorkspaceStore()

  // Auto-select first page if none active
  useEffect(() => {
    if (pages.length > 0 && !currentPageId) {
      const p = pages[0]
      setCurrentPage(p.id, p.idx)
      setScale(p.scale_label, p.scale_num)
    }
  }, [pages, currentPageId, setCurrentPage, setScale])

  // Load key plan floors on mount/project change
  useEffect(() => {
    if (projectId) {
      refetchKeyPlanFloors(currentPageId)
    }
  }, [projectId, currentPageId])

  // Query/Mutations: members
  const {
    members,
    isLoading: membersLoading,
    createMember,
    updateMember,
    deleteMember,
    bulkUpdateMembers,
    bulkDeleteMembers,
    analysePage,
    validateColumns,
  } = useMembers(currentPageId)

  // BOM items carry the fields SteelGenie's "Color By" tool actually colors
  // by once a build has run (Sequence / Weight / Labor Code / Paint) -- these
  // don't exist on the raw extracted member row, only on its BOM line item
  // (joined via member_id). Refetches whenever ['members'] is invalidated
  // (i.e. right after a build), same as everything else that depends on BOM.
  const { data: bomItems = [] } = useQuery({
    queryKey: ['bom-items-for-toolstrip', projectId],
    queryFn: () => bomApi.list(projectId),
    enabled: !!projectId,
  })
  const bomByMemberId = React.useMemo(() => {
    const map: Record<string, any> = {}
    for (const item of bomItems) {
      if (item.member_id) map[item.member_id] = item
    }
    return map
  }, [bomItems])
  const membersForToolStrip = React.useMemo(
    () =>
      members.map((m: any) => {
        const bom = bomByMemberId[m.id]
        return bom
          ? { ...m, sequence: bom.sequence, weight_lbs: bom.weight_lbs, labor_code: bom.labor_code, paint: bom.paint }
          : m
      }),
    [members, bomByMemberId]
  )



  const activePage = pages.find((p: any) => p.id === currentPageId) || null
  const [analysingState, setAnalysingState] = useState(false)
  const [extractingPageId, setExtractingPageId] = useState<string | null>(null)
  const [extractProgress, setExtractProgress] = useState<{ pct: number; msg: string } | null>(null)
  const queryClient = useQueryClient()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [leftTab, setLeftTab] = useState<'pages' | 'members'>('pages')

  // ── Key Plan (multi-page floor overlay) state ────────────────────────────
  const [showKeyPlan, setShowKeyPlan] = useState(false)
  const [keyPlanFloors, setKeyPlanFloors] = useState<KeyPlanFloor[]>([])
  const [activeFloorId, setActiveFloorId] = useState<string | null>(null)
  const [manualPageIds, setManualPageIds] = useState<Set<string>>(new Set())
  const [hiddenPageIds, setHiddenPageIds] = useState<Set<string>>(new Set())

  const refetchKeyPlanFloors = async (preferPageId?: string | null) => {
    try {
      const floors: KeyPlanFloor[] = await floorsApi.list(projectId)
      setKeyPlanFloors(floors || [])
      const pid = preferPageId ?? currentPageId
      const floorWithPage = pid ? floors.find((f) => f.pages.some((p) => p.page_id === pid)) : null
      setActiveFloorId((prev) => {
        if (floorWithPage) return floorWithPage.id
        if (prev && floors.some((f) => f.id === prev)) return prev
        return floors[0]?.id ?? null
      })
    } catch (err: any) {
      toast.error(err.message || 'Failed to load floors for Key Plan')
    }
  }

  const handleToggleKeyPlan = () => {
    setShowKeyPlan((prev) => {
      const next = !prev
      if (next) refetchKeyPlanFloors(currentPageId)
      return next
    })
  }

  const handleKeyPlanDragCommit = async (pageId: string, dxFt: number, dyFt: number) => {
    const floor = keyPlanFloors.find((f) => f.id === activeFloorId)
    const page = floor?.pages.find((p) => p.page_id === pageId)
    const reg = page?.registration
    if (!reg) return
    try {
      await floorsApi.overrideRegistration(pageId, { tx_ft: reg.tx_ft + dxFt, ty_ft: reg.ty_ft + dyFt })
      await refetchKeyPlanFloors()
    } catch (err: any) {
      toast.error(err.message || 'Failed to save manual alignment')
    }
  }

  const toggleManualPage = (pageId: string) => {
    setManualPageIds((prev) => {
      const next = new Set(prev)
      if (next.has(pageId)) next.delete(pageId)
      else next.add(pageId)
      return next
    })
  }

  const toggleHiddenPage = (pageId: string) => {
    setHiddenPageIds((prev) => {
      const next = new Set(prev)
      if (next.has(pageId)) next.delete(pageId)
      else next.add(pageId)
      return next
    })
  }

  // Card-level page updates (scale / T.O.S. / status) — keeps store in sync
  const handleCardUpdatePage = async (pageId: string, data: any) => {
    try {
      await updatePage({ pageId, data })
      if (pageId === currentPageId && (data.scale_label || data.scale_num)) {
        setScale(data.scale_label ?? selectedScale, data.scale_num ?? selectedRatio)
      }
      toast.success('Page settings saved')
    } catch (err: any) {
      toast.error(err.message || 'Failed to save page settings')
    }
  }

  // Card-level extract (play button on a page card)
  const handleCardExtract = async (page: any) => {
    if (!page.scale_num) {
      toast.error('Set a scale on this page first')
      return
    }
    setCurrentPage(page.id, page.idx)
    setScale(page.scale_label, page.scale_num)
    setExtractingPageId(page.id)
    setAnalysingState(true)
    toast.info('Starting member extraction job...', { id: 'analysis-toast' })
    try {
      const res = await membersApi.analyse(page.id, {
        scale_ratio: page.scale_num,
        detect_unlabeled: false,
        detect_braces: true,
        // 300 DPI: ~40% faster OCR on scanned sheets with acceptable accuracy.
        // Only affects raster pages; vector PDFs don't use OCR.
        ocr_dpi: 300,
        floor_elevation_ft: page.tos_ft ?? 12.0,
      })
      // Polling fallback: shows progress/completion even if WebSocket events are lost.
      if (res?.job_id) pollJob(res.job_id, page.id)
    } catch (err: any) {
      toast.error(err.message || 'Failed to start extraction job')
      setAnalysingState(false)
      setExtractingPageId(null)
    }
  }

  // Poll job status every 2s until done/failed (fallback when WS events are lost).
  const pollJob = (jobId: string, extractedPageId?: string) => {
    const started = Date.now()
    const timer = setInterval(async () => {
      try {
        const job = await jobsApi.get(jobId)
        if (!job) return
        if (job.status === 'running' || job.status === 'queued') {
          setExtractProgress({ pct: job.progress ?? 0, msg: job.message || 'Working…' })
          // Safety: if a dev-reload killed the worker, the job stays 'running' forever.
          if (Date.now() - started > 180_000) {
            clearInterval(timer)
            setAnalysingState(false)
            setExtractingPageId(null)
            setExtractProgress(null)
            toast.error(
              'Extraction timed out — the server may have restarted mid-job. Start the backend with "python run.py" and retry.',
              { id: 'analysis-toast', duration: 12000 }
            )
          }
          return
        }
        clearInterval(timer)
        setAnalysingState(false)
        setExtractingPageId(null)
        setExtractProgress(null)
        if (job.status === 'failed') {
          toast.error(`Extraction failed: ${job.error || 'unknown error'}`, { id: 'analysis-toast' })
        } else {
          toast.success(job.message || 'Member extraction completed!', { id: 'analysis-toast' })
          if (extractedPageId) clearPageDirty(extractedPageId)
          queryClient.invalidateQueries({ queryKey: ['members'] })
          queryClient.invalidateQueries({ queryKey: ['pages'] })
          // Live-merge this page's newly extracted members into the 3D
          // viewer's persistent scene immediately -- matches the reference
          // product, where the model updates the instant a sheet finishes
          // extracting instead of requiring a manual "Build"/reload.
          // MUST pass the page id: the 3D viewer's incremental loader keys
          // its "already loaded this page, skip" guard off lastEditedPageId,
          // so a bare bumpModelRefresh() here silently failed to re-merge a
          // re-extracted (or newly extracted alongside already-loaded) page.
          bumpModelRefresh(extractedPageId)
        }
      } catch {
        // transient polling error — keep trying until timeout
      }
    }, 2000)
  }

  // R: rotate selected column(s) by 90° (drafting detents)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (document.activeElement as HTMLElement)?.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key.toLowerCase() !== 'r' || e.ctrlKey || e.metaKey) return
      const cols = members.filter((m: any) => selection.has(m.id) && m.kind === 'column')
      if (cols.length === 0) return
      e.preventDefault()
      cols.forEach((c: any) =>
        updateMember({ id: c.id, data: { rotation: (((c.rotation || 0) + 90) % 360) } })
      )
      toast.info(`Rotated ${cols.length} column${cols.length > 1 ? 's' : ''} 90°`)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [members, selection, updateMember])

  // Listen to WebSocket events for job progress
  useEffect(() => {
    let ws: WebSocket | null = null

    const initWs = async () => {
      const {
        data: { session },
      } = await supabase.auth.getSession()
      // Dev fallback: backend accepts any token when Supabase isn't configured,
      // so always connect — otherwise progress events are never received locally.
      const token = session?.access_token || 'dev-token'

      const url = getEventsWebSocketUrl(token)
      ws = new WebSocket(url)

      ws.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'job.progress') {
            const { progress, message } = data.payload
            setExtractProgress({ pct: progress ?? 0, msg: message || '' })
            toast.info(`Analysis Progress: ${progress}% - ${message || ''}`, { id: 'analysis-toast' })
          } else if (data.type === 'job.done') {
            const { error, entity_id } = data.payload
            if (error) {
              toast.error(`Analysis failed: ${error}`, { id: 'analysis-toast' })
            } else {
              toast.success('Member extraction completed successfully!', { id: 'analysis-toast' })
              if (extractingPageId) clearPageDirty(extractingPageId)
              // Same fix as the polling path above: pass the page id so the
              // 3D viewer's incremental loader actually re-merges this page
              // instead of treating it as already-loaded and skipping it.
              bumpModelRefresh(extractingPageId ?? undefined)
            }
            setAnalysingState(false)
            setExtractingPageId(null)
            setExtractProgress(null)
            // Refetch members and pages without a full reload
            queryClient.invalidateQueries({ queryKey: ['members'] })
            queryClient.invalidateQueries({ queryKey: ['pages'] })
          }
        } catch {
          // ignore parsing error
        }
      }
    }

    initWs()

    return () => {
      if (ws) ws.close()
    }
  }, [currentPageId])

  // Keyboard review queue walker & shortcuts
  useEffect(() => {
    const handleReviewKeys = (e: KeyboardEvent) => {
      const activeEl = document.activeElement
      if (
        activeEl &&
        (activeEl.tagName === 'INPUT' ||
          activeEl.tagName === 'TEXTAREA' ||
          activeEl.tagName === 'SELECT' ||
          activeEl.getAttribute('contenteditable') === 'true')
      ) {
        return
      }

      const {
        selection,
        setSelection,
        clearSelection,
        setIsolation,
        showAllMembers,
        toggleMemberVisibility,
      } = useWorkspaceStore.getState()

      const queue = members.filter((m: any) => m.status !== 'excluded')
      if (queue.length === 0) return

      const selectedId = selection.size === 1 ? Array.from(selection)[0] : null
      const currentIndex = selectedId ? queue.findIndex((m: any) => m.id === selectedId) : -1

      switch (e.key.toLowerCase()) {
        case 'f':
          e.preventDefault()
          const searchInput = document.querySelector('input[placeholder*="Search members"]') as HTMLInputElement
          if (searchInput) {
            searchInput.focus()
          }
          break

        case 'i':
          e.preventDefault()
          if (selection.size > 0) {
            setIsolation({ ids: new Set(selection) })
            toast.info('Isolation mode active for selection')
          }
          break

        case 'h':
          e.preventDefault()
          if (selection.size > 0) {
            selection.forEach((id) => toggleMemberVisibility(id, false))
            clearSelection()
            toast.info('Selection hidden')
          }
          break

        case 'a': // Verify
          e.preventDefault()
          if (selection.size > 0) {
            const ids = Array.from(selection)
            bulkUpdateMembers({ ids, update: { status: 'verified' } })
              .then(() => toast.success(`Verified ${ids.length} member(s)`))
          }
          break

        case 'x': // Reject
          e.preventDefault()
          if (selection.size > 0) {
            const ids = Array.from(selection)
            bulkUpdateMembers({ ids, update: { status: 'rejected' } })
              .then(() => toast.success(`Rejected ${ids.length} member(s)`))
          }
          break

        case 'escape':
          e.preventDefault()
          clearSelection()
          setIsolation(null)
          toast.info('Selection and isolation cleared')
          break

        case 'arrowdown':
          e.preventDefault()
          let nextIdx = currentIndex + 1
          if (nextIdx >= queue.length) nextIdx = 0
          const nextMember = queue[nextIdx]
          setSelection(new Set([nextMember.id]))
          useWorkspaceStore.getState().setZoomTarget(nextMember.id)
          break

        case 'arrowup':
          e.preventDefault()
          let prevIdx = currentIndex - 1
          if (prevIdx < 0) prevIdx = queue.length - 1
          const prevMember = queue[prevIdx]
          setSelection(new Set([prevMember.id]))
          useWorkspaceStore.getState().setZoomTarget(prevMember.id)
          break

        default:
          break
      }

      if (e.altKey && e.key.toLowerCase() === 'h') {
        e.preventDefault()
        showAllMembers()
        toast.info('All members shown')
      }
    }

    window.addEventListener('keydown', handleReviewKeys)
    return () => {
      window.removeEventListener('keydown', handleReviewKeys)
    }
  }, [members, bulkUpdateMembers])

  // Canvas tool keyboard shortcuts
  useEffect(() => {
    const handleToolShortcuts = (e: KeyboardEvent) => {
      const activeEl = document.activeElement
      if (
        activeEl &&
        (activeEl.tagName === 'INPUT' ||
          activeEl.tagName === 'TEXTAREA' ||
          activeEl.tagName === 'SELECT' ||
          activeEl.getAttribute('contenteditable') === 'true')
      ) {
        return
      }

      const { setTool } = useWorkspaceStore.getState()
      
      switch (e.key.toLowerCase()) {
        // Remap workspace tool selection keyboard shortcuts
        case 'h':
          // Keep hand key
          setTool('hand')
          toast.info('Tool: Hand pan active')
          break
        case 'r':
          setTool('ruler')
          toast.info('Tool: Ruler active')
          break
        case 'b':
          setTool('beam')
          toast.info('Tool: Draw Beam active')
          break
        case 'c':
          setTool('column')
          toast.info('Tool: Place Column active')
          break
        case 'v':
          setTool('brace')
          toast.info('Tool: Draw Brace active')
          break
        case 'm':
          setTool('marker')
          toast.info('Tool: Annotation Marker active')
          break
        default:
          break
      }
    }

    window.addEventListener('keydown', handleToolShortcuts)
    return () => {
      window.removeEventListener('keydown', handleToolShortcuts)
    }
  }, [])

  // Load layer presets from server
  useEffect(() => {
    if (!projectId) return
    layerPresetsApi
      .list(projectId)
      .then((serverPresets) => {
        if (serverPresets && serverPresets.length > 0) {
          const formatted = serverPresets.map((p: any) => ({
            id: p.id,
            name: p.name,
            classVisibility: p.payload.classVisibility,
            classOpacity: p.payload.classOpacity,
            classColors: p.payload.classColors,
            aids: p.payload.aids,
            colorMode: p.payload.colorMode
          }))
          useWorkspaceStore.getState().setPresetsFromServer(formatted)
        }
      })
      .catch(() => {
        // ignore background fetch error
      })
  }, [projectId])

  const handleScaleChange = async (label: string, ratio: number) => {
    if (!currentPageId) return
    setScale(label, ratio)
    try {
      await updatePage({
        pageId: currentPageId,
        data: { scale_label: label, scale_num: ratio },
      })
      toast.success(`Scale updated to ${label}`)
    } catch {
      toast.error('Failed to save scale setting')
    }
  }

  const handleRunAnalyse = async (detectUnlabeled: boolean, elevation: number) => {
    if (!currentPageId || !selectedRatio) return
    setAnalysingState(true)
    toast.info('Starting member extraction job...', { id: 'analysis-toast' })
    try {
      await updatePage({
        pageId: currentPageId,
        data: { tos_ft: elevation },
      })

      if (currentPageId) setExtractingPageId(currentPageId)
      const res = await analysePage({
        scale_ratio: selectedRatio,
        detect_unlabeled: detectUnlabeled,
        detect_braces: true,
        ocr_dpi: 300,
        floor_elevation_ft: elevation,
      })
      if (res?.job_id) pollJob(res.job_id)
    } catch (err: any) {
      toast.error(err.message || 'Failed to start analysis job')
      setAnalysingState(false)
      setExtractingPageId(null)
    }
  }

  const handleMemberSelect = (m: any | null) => {
    if (!m) {
      clearSelection()
    }
  }

  const calculateLengthFt = (x1: number, y1: number, x2: number, y2: number) => {
    if (!imageNaturalWidth || !selectedRatio) return null
    const dxPx = (x2 - x1) * imageNaturalWidth
    const dyPx = (y2 - y1) * imageNaturalWidth * imageAspect
    const lenPts = (Math.sqrt(dxPx * dxPx + dyPx * dyPx) * 72) / 150
    return (lenPts * selectedRatio) / 864
  }

  const handleMemberDragEnd = async (id: string, dx: number, dy: number) => {
    try {
      const existing = members.find((m: any) => m.id === id)
      if (!existing) return

      const updatedGeometry = { ...existing.geometry }
      const hasSpan = existing.geometry.bx1 !== undefined && existing.geometry.bx1 !== null &&
                      existing.geometry.bx2 !== undefined && existing.geometry.bx2 !== null

      if (hasSpan) {
        updatedGeometry.bx1 = (existing.geometry.bx1 || 0) + dx
        updatedGeometry.by1 = (existing.geometry.by1 || 0) + dy
        updatedGeometry.bx2 = (existing.geometry.bx2 || 0) + dx
        updatedGeometry.by2 = (existing.geometry.by2 || 0) + dy
        if (existing.geometry.x !== undefined && existing.geometry.x !== null) {
          updatedGeometry.x = existing.geometry.x + dx
        }
        if (existing.geometry.y !== undefined && existing.geometry.y !== null) {
          updatedGeometry.y = existing.geometry.y + dy
        }
      } else {
        updatedGeometry.x = (existing.geometry.x || 0) + dx
        updatedGeometry.y = (existing.geometry.y || 0) + dy
      }

      await updateMember({
        id,
        data: { geometry: updatedGeometry }
      })
      await validateColumns()
      pushHistoryLog('move', `Move ${existing.piecemark || existing.section || existing.kind}`)
      if (currentPageId) markPageDirty(currentPageId)
      toast.success('Member position updated')
    } catch {
      toast.error('Failed to update member position')
    }
  }

  const handleEndpointDragEnd = async (id: string, endpoint: 'start' | 'end', x: number, y: number) => {
    try {
      const existing = members.find((m: any) => m.id === id)
      if (!existing) return

      const newBx1 = endpoint === 'start' ? x : (existing.geometry.bx1 || 0)
      const newBy1 = endpoint === 'start' ? y : (existing.geometry.by1 || 0)
      const newBx2 = endpoint === 'end' ? x : (existing.geometry.bx2 || 0)
      const newBy2 = endpoint === 'end' ? y : (existing.geometry.by2 || 0)

      let newAngle = (Math.atan2(newBy2 - newBy1, newBx2 - newBx1) * 180) / Math.PI
      if (newAngle > 90) newAngle -= 180
      if (newAngle < -90) newAngle += 180

      const newBeamDir = Math.abs(newBx2 - newBx1) >= Math.abs(newBy2 - newBy1) ? 'H' : 'V'

      const updatedGeometry = {
        ...existing.geometry,
        bx1: newBx1,
        by1: newBy1,
        bx2: newBx2,
        by2: newBy2,
        x: (newBx1 + newBx2) / 2,
        y: (newBy1 + newBy2) / 2,
        angle_deg: newAngle,
        beam_dir: newBeamDir,
      }

      const calculatedLength = calculateLengthFt(newBx1, newBy1, newBx2, newBy2)

      await updateMember({
        id,
        data: {
          geometry: updatedGeometry,
          length_ft: calculatedLength !== null ? calculatedLength : existing.length_ft,
        }
      })
      pushHistoryLog('resize', `Resize ${existing.piecemark || existing.section || existing.kind}`)
      if (currentPageId) markPageDirty(currentPageId)
      toast.success('Member endpoints updated')
    } catch {
      toast.error('Failed to update member endpoints')
    }
  }

  const handleAddAnnotationMarker = async (pt: any) => {
    try {
      await createMember({
        kind: 'beam',
        section: 'W12X26',
        geometry: { x: pt.x, y: pt.y },
        length_ft: 10.0,
      })
      toast.success('Annotation marker added')
    } catch {
      toast.error('Failed to add manual member marker')
    }
  }

  const [calibLine, setCalibLine] = useState<any | null>(null)
  const { imageNaturalWidth, imageAspect } = useWorkspaceStore()

  const handleRulerCalibrate = (line: any) => {
    setCalibLine(line)
  }

  const handleApplyCalibratedScale = async (label: string, ratio: number) => {
    setCalibLine(null)
    if (!currentPageId) return
    await handleCardUpdatePage(currentPageId, { scale_label: label, scale_num: ratio })
  }

  const KIND_DEFAULT_SECTION: Record<string, string> = {
    column: 'W10X49',
    beam: 'W12X26',
    brace: 'HSS5X5X5/16',
    joist: 'K-SERIES',
    hbrace: 'HSS5X5X5/16',
  }

  const KIND_API_MAP: Record<string, string> = {
    brace: 'vbrace',
    hbrace: 'hbrace',
    joist: 'joist',
    column: 'column',
    beam: 'beam',
  }

  const handleDrawMember = async (kind: 'column' | 'beam' | 'brace' | 'joist' | 'hbrace', geom: any) => {
    let lengthFt: number | null = null
    if (selectedRatio && imageNaturalWidth && kind !== 'column') {
      const wPx = imageNaturalWidth
      const hPx = imageNaturalWidth * imageAspect
      const dxPx = (geom.x2 - geom.x1) * wPx
      const dyPx = (geom.y2 - geom.y1) * hPx
      const lenPts = (Math.sqrt(dxPx * dxPx + dyPx * dyPx) * 72) / 150
      lengthFt = Math.round(((lenPts * selectedRatio) / 864) * 100) / 100
    }
    try {
      const created = await createMember({
        kind: KIND_API_MAP[kind] || kind,
        section: KIND_DEFAULT_SECTION[kind],
        source: 'manual',
        status: 'need_review',
        rotation: kind === 'column' ? 90 : 0,
        geometry: {
          x: (geom.x1 + geom.x2) / 2,
          y: (geom.y1 + geom.y2) / 2,
          bx1: geom.x1,
          by1: geom.y1,
          bx2: geom.x2,
          by2: geom.y2,
        },
        length_ft: lengthFt,
      })
      if (created?.id) setSelection(new Set([created.id]))
      pushHistoryLog('add', `Add ${kind[0].toUpperCase() + kind.slice(1)}`)
      if (currentPageId) markPageDirty(currentPageId)
      toast.success(`${kind[0].toUpperCase() + kind.slice(1)} added — set its section in the panel`)
    } catch (err: any) {
      toast.error(err.message || 'Failed to add member')
    }
  }

  const handleMemberUpdate = async (id: string, data: any) => {
    try {
      const existing = members.find((m: any) => m.id === id)
      await updateMember({ id, data })
      pushHistoryLog('edit', `Edit ${existing?.piecemark || existing?.section || existing?.kind || 'member'}`)
      if (currentPageId) markPageDirty(currentPageId)
      toast.success('Member properties saved')
    } catch {
      toast.error('Failed to update member properties')
    }
  }

  const handleMemberDelete = async (id: string) => {
    try {
      const existing = members.find((m: any) => m.id === id)
      await deleteMember(id)
      pushHistoryLog('delete', `Delete ${existing?.piecemark || existing?.section || existing?.kind || 'member'}`)
      if (currentPageId) markPageDirty(currentPageId)
      toast.success('Member deleted')
    } catch {
      toast.error('Failed to delete member')
    }
  }

  const handleBulkUpdate = async (args: { ids: string[]; update: any }) => {
    try {
      await bulkUpdateMembers(args)
      pushHistoryLog('edit', `Edit ${args.ids.length} member${args.ids.length === 1 ? '' : 's'}`)
      if (currentPageId) markPageDirty(currentPageId)
      toast.success('Selected members updated successfully')
    } catch (err: any) {
      toast.error(err.message || 'Failed to update members in bulk')
    }
  }

  const handlePropertiesBulkUpdate = async (ids: string[], update: any) => {
    try {
      await bulkUpdateMembers({ ids, update })
      pushHistoryLog('edit', `Edit ${ids.length} member${ids.length === 1 ? '' : 's'}`)
      if (currentPageId) markPageDirty(currentPageId)
      toast.success('Selected members updated successfully')
    } catch (err: any) {
      toast.error(err.message || 'Failed to update members in bulk')
    }
  }

  const handleBulkDelete = async (ids: string[]) => {
    try {
      await bulkDeleteMembers(ids)
      pushHistoryLog('delete', `Delete ${ids.length} member${ids.length === 1 ? '' : 's'}`)
      if (currentPageId) markPageDirty(currentPageId)
      toast.success('Selected members deleted successfully')
      clearSelection()
    } catch (err: any) {
      toast.error(err.message || 'Failed to delete members in bulk')
    }
  }

  // Listen for 'R' key to rotate the selected column 90 degrees,
  // and Backspace/Delete to delete the selected member(s)
  useEffect(() => {
    const handleKeyDown = async (e: KeyboardEvent) => {
      // Ignore if user is typing in an input or textarea
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement).isContentEditable) {
        return
      }

      if (e.key === 'r' || e.key === 'R') {
        const selectedIds = Array.from(selection)
        if (selectedIds.length === 1) {
          const id = selectedIds[0]
          const selectedMember = members.find((m: any) => m.id === id)
          if (selectedMember && selectedMember.kind === 'column') {
            e.preventDefault()
            const currentRotation = selectedMember.rotation || 0
            const nextRotation = (currentRotation + 90) % 180 // toggle between 0 and 90
            try {
              await updateMember({ 
                id, 
                data: { rotation: nextRotation } 
              })
              toast.success(`Rotated column to ${nextRotation}°`)
            } catch {
              toast.error('Failed to rotate column')
            }
          }
        }
      } else if (e.key === 'Backspace' || e.key === 'Delete') {
        const selectedIds = Array.from(selection)
        if (selectedIds.length > 0) {
          e.preventDefault()
          await handleBulkDelete(selectedIds)
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [selection, members, updateMember, handleBulkDelete])

  // "Clean" (Members panel header) -- wipe every extracted member on the
  // active page and reset its status so it can be re-extracted from
  // scratch. Distinct from bulk-delete-selection: this always targets the
  // whole current page regardless of what's selected.
  const handleCleanPage = async () => {
    if (!activePage || members.length === 0) return
    if (!confirm(`Delete all ${members.length} extracted members on this page and reset it? This can't be undone.`)) return
    try {
      await bulkDeleteMembers(members.map((m: any) => m.id))
      await updatePage({ pageId: activePage.id, data: { status: 'not_started' } })
      clearSelection()
      toast.success('Page cleaned — ready to re-extract')
    } catch (err: any) {
      toast.error(err.message || 'Failed to clean page')
    }
  }

  // Find other pages on the active floor
  const floorPages = React.useMemo(() => {
    const activeFloor = keyPlanFloors.find((f) => f.pages.some((p) => p.page_id === currentPageId))
    if (!activeFloor) return []
    return activeFloor.pages.map((fp: any) => {
      const pageObj = pages.find((p: any) => p.id === fp.page_id)
      return {
        id: fp.page_id,
        image_url: pageObj?.image_url || null,
        sheet_no: fp.sheet_no,
        title: fp.title,
        registration: fp.registration || {
          tx_ft: 0,
          ty_ft: 0,
          ft_per_pct_x: pageObj?.scale_num ? 100 / pageObj.scale_num : 1.0,
          ft_per_pct_y: pageObj?.scale_num ? 100 / pageObj.scale_num : 1.0,
          rotation_deg: 0,
        },
      }
    })
  }, [keyPlanFloors, currentPageId, pages])

  return (
    <div style={{ display: 'flex', height: '100%', width: '100%', overflow: 'hidden' }}>
      {/* Integrated Left Sidebar: Navigation (Pages / Members) */}
      <NavigationPanel
        sidebarOpen={sidebarOpen}
        setSidebarOpen={setSidebarOpen}
        leftTab={leftTab}
        setLeftTab={setLeftTab}
        membersCount={members.length}
        pagesTabContent={
          <PageRail
            projectId={projectId}
            pages={pages}
            isLoading={workspaceLoading}
            refetchWorkspace={() => {
              queryClient.invalidateQueries({ queryKey: ['drawings', projectId] })
              queryClient.invalidateQueries({ queryKey: ['pages'] })
            }}
            onUpdatePage={handleCardUpdatePage}
            onExtract={handleCardExtract}
            extractingPageId={extractingPageId}
            extractProgress={extractProgress}
          />
        }
        membersTabContent={
          <MembersTab
            members={members}
            activePage={activePage}
            onClean={handleCleanPage}
            onBuild={() => activePage && handleCardExtract(activePage)}
            isBuilding={!!activePage && extractingPageId === activePage.id}
          />
        }
      />

      {/* Center workspace canvas */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <CanvasToolbar
          onScaleChange={handleScaleChange}
          onRunAnalyse={handleRunAnalyse}
          isAnalysing={analysingState}
        />
        <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
          <div
            style={{
              position: 'absolute',
              top: '16px',
              left: '12px',
              zIndex: 30,
              transition: 'left 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
            }}
          >
            <VerticalToolStrip
              members={membersForToolStrip}
              projectId={projectId}
              sidebarOpen={sidebarOpen}
              onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
              showKeyPlan={showKeyPlan}
              onToggleKeyPlan={handleToggleKeyPlan}
            />
          </div>
          {showKeyPlan ? (
            <KeyPlanView
              floor={keyPlanFloors.find((f) => f.id === activeFloorId) || null}
              manualPageIds={manualPageIds}
              hiddenPageIds={hiddenPageIds}
              onDragCommit={handleKeyPlanDragCommit}
            />
          ) : (
            <PlanCanvas
              imageUrl={activePage?.image_url || null}
              members={membersForToolStrip}
              onMemberSelect={handleMemberSelect}
              onAddAnnotationMarker={handleAddAnnotationMarker}
              onRulerCalibrate={handleRulerCalibrate}
              onDrawMember={handleDrawMember}
              onMemberDragEnd={handleMemberDragEnd}
              onEndpointDragEnd={handleEndpointDragEnd}
              floorPages={floorPages}
              currentPageId={currentPageId}
            />
          )}

          {calibLine && imageNaturalWidth && (
            <ScaleCalibrationModal
              line={calibLine}
              imageNaturalWidth={imageNaturalWidth}
              imageAspect={imageAspect}
              onApply={handleApplyCalibratedScale}
              onClose={() => setCalibLine(null)}
            />
          )}
        </div>
      </div>

      {/* Right dock: Sheet Summary when nothing selected, Properties when
          editing, Key Plan panel when the Key Plan tool is active. Hidden
          entirely while the 3D pane is open — with 3D on, the screen is
          just [2D drawing | 3D view], and the 3D pane has its own
          Properties dock (opened via its own corner toggle) instead. */}
      {!show3d && showKeyPlan && (
        <KeyPlanPropertiesPanel
          projectId={projectId}
          floors={keyPlanFloors}
          activeFloorId={activeFloorId}
          onSelectFloor={setActiveFloorId}
          manualPageIds={manualPageIds}
          onToggleManual={toggleManualPage}
          hiddenPageIds={hiddenPageIds}
          onToggleHidden={toggleHiddenPage}
          onApplied={() => refetchKeyPlanFloors()}
          onClose={() => setShowKeyPlan(false)}
        />
      )}
      {!show3d && !showKeyPlan && (
        selection.size > 0 ? (
          <PropertiesPanel
            selection={selection}
            members={members}
            onUpdate={handleMemberUpdate}
            onDelete={handleMemberDelete}
            onBulkUpdate={handlePropertiesBulkUpdate}
            onBulkDelete={handleBulkDelete}
            onClose={clearSelection}
            pageTos={activePage?.tos_ft || 12.0}
          />
        ) : (
          <SheetSummary members={members} />
        )
      )}
    </div>
  )
}
