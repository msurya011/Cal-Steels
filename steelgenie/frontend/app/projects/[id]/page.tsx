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
import { MemberExplorer } from '../../../features/workspace/components/MemberExplorer/MemberExplorer'
import { SummaryBar } from '../../../features/workspace/components/SummaryBar'
import { PropertiesPanel } from '../../../features/workspace/components/PropertiesPanel'
import { ScaleCalibrationModal } from '../../../features/workspace/components/ScaleCalibrationModal'
import { SheetSummary } from '../../../features/workspace/components/SheetSummary'
import { VerticalToolStrip } from '../../../features/workspace/components/VerticalToolStrip'
import { supabase } from '../../../lib/supabase'
import { getEventsWebSocketUrl, jobsApi, membersApi, layerPresetsApi } from '../../../lib/api'
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
    validateColumns,
  } = useMembers(currentPageId)

  // Listen for 'R' key to rotate the selected column 90 degrees
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
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
    }
  }, [selection, members, updateMember])

  const activePage = pages.find((p: any) => p.id === currentPageId) || null
  const [analysingState, setAnalysingState] = useState(false)
  const [extractingPageId, setExtractingPageId] = useState<string | null>(null)
  const [extractProgress, setExtractProgress] = useState<{ pct: number; msg: string } | null>(null)
  const queryClient = useQueryClient()
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [leftTab, setLeftTab] = useState<'pages' | 'members'>('pages')

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
    if (m) {
      toggleSelection(m.id)
    } else {
      clearSelection()
    }
  }

  const handleMemberDragEnd = async (id: string, newX: number, newY: number) => {
    try {
      const existing = members.find((m: any) => m.id === id)
      if (!existing) return
      await updateMember({ 
        id, 
        data: { geometry: { ...existing.geometry, x: newX, y: newY } } 
      })
      await validateColumns()
      toast.success('Member position updated and snapped')
    } catch {
      toast.error('Failed to update member position')
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
      {/* Integrated Left Sidebar: Navigation (Pages / Members) */}
      {sidebarOpen && (
        <div
          style={{
            width: '270px',
            backgroundColor: '#111827',
            borderRight: '1px solid rgba(59, 130, 246, 0.1)',
            display: 'flex',
            flexDirection: 'column',
            height: '100%',
            flexShrink: 0,
          }}
        >
          {/* Sidebar Header */}
          <div
            style={{
              height: '48px',
              borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              padding: '0 16px',
              backgroundColor: '#0F172A',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#F1F5F9' }}>
              <Columns size={16} style={{ color: '#3B82F6' }} />
              <span style={{ fontSize: '13px', fontWeight: 700 }}>Navigation</span>
            </div>
            <button
              onClick={() => setSidebarOpen(false)}
              style={{
                background: 'none',
                border: 'none',
                color: '#64748B',
                cursor: 'pointer',
                fontSize: '18px',
                lineHeight: 1,
                padding: '2px',
              }}
              title="Close Navigation"
            >
              &times;
            </button>
          </div>

          {/* Capsule Segmented Tabs Control */}
          <div style={{ padding: '12px 16px', backgroundColor: '#111827' }}>
            <div
              style={{
                display: 'flex',
                backgroundColor: '#0F172A',
                padding: '4px',
                borderRadius: '24px',
                border: '1px solid rgba(59, 130, 246, 0.15)',
              }}
            >
              <button
                onClick={() => setLeftTab('pages')}
                style={{
                  flex: 1,
                  backgroundColor: leftTab === 'pages' ? '#1B3A60' : 'transparent',
                  color: leftTab === 'pages' ? '#FFFFFF' : '#94A3B8',
                  border: leftTab === 'pages' ? '1px solid rgba(59, 130, 246, 0.3)' : 'none',
                  borderRadius: '20px',
                  padding: '6px 12px',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  outline: 'none',
                  transition: 'all 0.2s ease',
                }}
              >
                Pages
              </button>
              <button
                onClick={() => setLeftTab('members')}
                style={{
                  flex: 1,
                  backgroundColor: leftTab === 'members' ? '#1B3A60' : 'transparent',
                  color: leftTab === 'members' ? '#FFFFFF' : '#94A3B8',
                  border: leftTab === 'members' ? '1px solid rgba(59, 130, 246, 0.3)' : 'none',
                  borderRadius: '20px',
                  padding: '6px 12px',
                  fontSize: '11px',
                  fontWeight: 700,
                  cursor: 'pointer',
                  outline: 'none',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.2s ease',
                }}
              >
                <span>Members</span>
                <span
                  style={{
                    backgroundColor: '#F59E0B',
                    color: '#0F172A',
                    padding: '2px 6px',
                    borderRadius: '10px',
                    fontSize: '10px',
                    fontWeight: 800,
                    marginLeft: '6px',
                    lineHeight: 1,
                  }}
                >
                  {members.length}
                </span>
              </button>
            </div>
          </div>

          {/* Sidebar Content */}
          <div style={{ flex: 1, overflow: 'hidden' }}>
            {leftTab === 'pages' ? (
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
            ) : (
              <MemberExplorer
                members={members}
                bulkUpdateMembers={handleBulkUpdate}
                bulkDeleteMembers={handleBulkDelete}
              />
            )}
          </div>
        </div>
      )}

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
              members={members}
              projectId={projectId}
              sidebarOpen={sidebarOpen}
              onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
            />
          </div>
          <PlanCanvas
            imageUrl={activePage?.image_url || null}
            members={members}
            onMemberSelect={handleMemberSelect}
            onAddAnnotationMarker={handleAddAnnotationMarker}
            onRulerCalibrate={handleRulerCalibrate}
            onDrawMember={handleDrawMember}
            onMemberDragEnd={handleMemberDragEnd}
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
