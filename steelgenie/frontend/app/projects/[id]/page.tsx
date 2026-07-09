'use client'

import React, { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { useWorkspaceStore } from '../../../lib/stores/workspaceStore'
import { useWorkspace } from '../../../features/workspace/hooks/useWorkspace'
import { useMembers } from '../../../features/workspace/hooks/useMembers'
import { PageRail } from '../../../features/workspace/components/PageRail/PageRail'
import { CanvasToolbar } from '../../../features/workspace/components/CanvasToolbar'
import { PlanCanvas } from '../../../features/workspace/components/PlanCanvas/PlanCanvas'
import { MemberExplorer } from '../../../features/workspace/components/MemberExplorer/MemberExplorer'
import { SummaryBar } from '../../../features/workspace/components/SummaryBar'
import { PropertiesPanel } from '../../../features/workspace/components/PropertiesPanel'
import { ScaleCalibrationModal } from '../../../features/workspace/components/ScaleCalibrationModal'
import { SheetSummary } from '../../../features/workspace/components/SheetSummary'
import { VerticalToolStrip } from '../../../features/workspace/components/VerticalToolStrip'
import { supabase } from '../../../lib/supabase'
import { getEventsWebSocketUrl, jobsApi, membersApi } from '../../../lib/api'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'

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
  } = useWorkspaceStore()

  // Auto-select first page if none active
  useEffect(() => {
    if (pages.length > 0 && !currentPageId) {
      const p = pages[0]
      setCurrentPage(p.id, p.idx)
      setScale(p.scale_label, p.scale_num)
    }
  }, [pages, currentPageId, setCurrentPage, setScale])

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
  } = useMembers(currentPageId)

  const activePage = pages.find((p: any) => p.id === currentPageId) || null
  const [analysingState, setAnalysingState] = useState(false)
  const [extractingPageId, setExtractingPageId] = useState<string | null>(null)
  const [extractProgress, setExtractProgress] = useState<{ pct: number; msg: string } | null>(null)
  const queryClient = useQueryClient()

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
      if (res?.job_id) pollJob(res.job_id)
    } catch (err: any) {
      toast.error(err.message || 'Failed to start extraction job')
      setAnalysingState(false)
      setExtractingPageId(null)
    }
  }

  // Poll job status every 2s until done/failed (fallback when WS events are lost).
  const pollJob = (jobId: string) => {
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
          queryClient.invalidateQueries({ queryKey: ['members'] })
          queryClient.invalidateQueries({ queryKey: ['pages'] })
        }
      } catch {
        // transient polling error — keep trying until timeout
      }
    }, 2000)
  }

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
    if (m) {
      toggleSelection(m.id)
    } else {
      clearSelection()
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
  }

  const handleDrawMember = async (kind: 'column' | 'beam' | 'brace', geom: any) => {
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
        kind: kind === 'brace' ? 'vbrace' : kind,
        section: KIND_DEFAULT_SECTION[kind],
        source: 'manual',
        status: 'need_review',
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
      toast.success(`${kind[0].toUpperCase() + kind.slice(1)} added — set its section in the panel`)
    } catch (err: any) {
      toast.error(err.message || 'Failed to add member')
    }
  }

  const handleMemberUpdate = async (id: string, data: any) => {
    try {
      await updateMember({ id, data })
      toast.success('Member properties saved')
    } catch {
      toast.error('Failed to update member properties')
    }
  }

  const handleMemberDelete = async (id: string) => {
    try {
      await deleteMember(id)
      toast.success('Member deleted')
    } catch {
      toast.error('Failed to delete member')
    }
  }

  const handleBulkUpdate = async (args: { ids: string[]; update: any }) => {
    try {
      await bulkUpdateMembers(args)
      toast.success('Selected members updated successfully')
    } catch (err: any) {
      toast.error(err.message || 'Failed to update members in bulk')
    }
  }

  const handlePropertiesBulkUpdate = async (ids: string[], update: any) => {
    try {
      await bulkUpdateMembers({ ids, update })
      toast.success('Selected members updated successfully')
    } catch (err: any) {
      toast.error(err.message || 'Failed to update members in bulk')
    }
  }

  const handleBulkDelete = async (ids: string[]) => {
    try {
      await bulkDeleteMembers(ids)
      toast.success('Selected members deleted successfully')
      clearSelection()
    } catch (err: any) {
      toast.error(err.message || 'Failed to delete members in bulk')
    }
  }

  return (
    <div style={{ display: 'flex', height: '100%', width: '100%', overflow: 'hidden' }}>
      {/* Left Sidebar: Pages rail */}
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

      {/* Second Sidebar: Member Explorer (placed where marked in red) */}
      <div
        style={{
          width: '260px',
          backgroundColor: '#111827',
          borderRight: '1px solid rgba(59, 130, 246, 0.1)',
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            height: '42px',
            borderBottom: '1px solid rgba(59, 130, 246, 0.1)',
            display: 'flex',
            alignItems: 'center',
            padding: '0 16px',
            backgroundColor: '#0F172A',
            fontWeight: 700,
            fontSize: '12px',
            color: '#F1F5F9',
          }}
        >
          Members ({members.length})
        </div>
        <div style={{ flex: 1, overflow: 'hidden' }}>
          <MemberExplorer
            members={members}
            bulkUpdateMembers={handleBulkUpdate}
            bulkDeleteMembers={handleBulkDelete}
          />
        </div>
      </div>

      {/* Center workspace canvas */}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
        <CanvasToolbar
          onScaleChange={handleScaleChange}
          onRunAnalyse={handleRunAnalyse}
          isAnalysing={analysingState}
        />

        <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
          <VerticalToolStrip />
          <PlanCanvas
            imageUrl={activePage?.image_url || null}
            members={members}
            onMemberSelect={handleMemberSelect}
            onAddAnnotationMarker={handleAddAnnotationMarker}
            onRulerCalibrate={handleRulerCalibrate}
            onDrawMember={handleDrawMember}
          />

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

        <SummaryBar members={members} />
      </div>

      {/* Right dock: Sheet Summary when nothing selected, Properties when editing */}
      {selection.size > 0 ? (
        <PropertiesPanel
          selection={selection}
          members={members}
          onUpdate={handleMemberUpdate}
          onDelete={handleMemberDelete}
          onBulkUpdate={handlePropertiesBulkUpdate}
          onBulkDelete={handleBulkDelete}
          onClose={clearSelection}
        />
      ) : (
        <SheetSummary members={members} />
      )}
    </div>
  )
}
