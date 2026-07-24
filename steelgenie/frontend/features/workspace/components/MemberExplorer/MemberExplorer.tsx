import React, { useState, useEffect, useRef } from 'react'
import {
  Search,
  Eye,
  EyeOff,
  Target,
  ChevronDown,
  ChevronRight,
  Check,
  AlertTriangle,
  Trash2,
  CheckSquare,
  Square,
  MinusSquare,
  Sparkles,
  Play,
  Loader2,
} from 'lucide-react'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'
import { sectionsApi } from '../../../../lib/api'
import { toast } from 'sonner'

interface Member {
  id: string
  kind: string
  section: string | null
  grade: string | null
  rotation: number
  length_ft: number | null
  geometry: any
  confidence?: number | null
  status?: string
  source?: string
  piecemark?: string | null
}

interface ActivePage {
  id: string
  idx?: number
  title?: string | null
  sheet_no?: string | null
  status?: string
}

interface MemberExplorerProps {
  members: Member[]
  bulkUpdateMembers: (args: { ids: string[]; update: any }) => Promise<any>
  bulkDeleteMembers: (ids: string[]) => Promise<any>
  activePage?: ActivePage | null
  onClean?: () => void
  onBuild?: () => void
  isBuilding?: boolean
}

export function MemberExplorer({
  members,
  bulkUpdateMembers,
  bulkDeleteMembers,
  activePage,
  onClean,
  onBuild,
  isBuilding,
}: MemberExplorerProps) {
  const {
    selection,
    hiddenIds,
    isolation,
    searchQuery,
    setSelection,
    toggleSelection,
    clearSelection,
    toggleMemberVisibility,
    showAllMembers,
    setIsolation,
    setColorMode,
    setSearchQuery,
    setZoomTarget,
    layers,
    toggleLayerVisibility,
  } = useWorkspaceStore()

  // Tree collapse states -- collapsed by default (SteelGenie shows category
  // totals first; you drill in via the chevron rather than always seeing
  // every member listed out).
  const [expandedKinds, setExpandedKinds] = useState<Record<string, boolean>>({
    beam: false,
    column: false,
    brace: false,
    joist: false,
  })
  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({})

  // Bulk edit state
  const [bulkSection, setBulkSection] = useState('')
  const [bulkStatus, setBulkStatus] = useState('')
  const [suggestions, setSuggestions] = useState<any[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const [updating, setUpdating] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Autocomplete suggest click outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Filter members by search query
  const filteredMembers = members.filter((m) => {
    if (!searchQuery) return true
    const q = searchQuery.toLowerCase()
    const matchPiecemark = m.piecemark ? m.piecemark.toLowerCase().includes(q) : false
    const matchSection = m.section ? m.section.toLowerCase().includes(q) : false
    const matchKind = m.kind.toLowerCase().includes(q)
    return matchPiecemark || matchSection || matchKind
  })

  // Group by category (beam, column, brace (vbrace/hbrace), joist)
  const grouped: Record<string, Record<string, Member[]>> = {
    beam: {},
    column: {},
    brace: {},
    joist: {},
  }

  filteredMembers.forEach((m) => {
    let cat = 'beam'
    if (m.kind === 'column') cat = 'column'
    else if (m.kind === 'vbrace' || m.kind === 'hbrace' || m.kind === 'brace') cat = 'brace'
    else if (m.kind === 'joist') cat = 'joist'

    const sec = m.section || 'Unlabelled'
    if (!grouped[cat][sec]) {
      grouped[cat][sec] = []
    }
    grouped[cat][sec].push(m)
  })

  const getCategoryLabel = (cat: string) => {
    return {
      beam: 'Beams',
      column: 'Columns',
      brace: 'Braces',
      joist: 'Joists',
    }[cat] || cat
  }

  const toggleKindCollapse = (kind: string) => {
    setExpandedKinds((prev) => ({ ...prev, [kind]: !prev[kind] }))
  }

  const toggleSectionCollapse = (secKey: string) => {
    setExpandedSections((prev) => ({ ...prev, [secKey]: !prev[secKey] }))
  }

  // Kind level selection helpers
  const getKindMembers = (kind: string): Member[] => {
    const sections = grouped[kind]
    const list: Member[] = []
    Object.values(sections).forEach((mList) => list.push(...mList))
    return list
  }

  // Badge count shown next to each category total -- members with a
  // resolved section designation (i.e. not still "Unlabelled"), matching
  // SteelGenie's category badges (e.g. "Columns (80) [78]").
  const getKindLabeledCount = (kind: string): number =>
    getKindMembers(kind).filter((m) => !!m.section).length

  const getKindSelectionState = (kind: string) => {
    const mList = getKindMembers(kind)
    if (mList.length === 0) return 'none'
    const selectedCount = mList.filter((m) => selection.has(m.id)).length
    if (selectedCount === 0) return 'none'
    if (selectedCount === mList.length) return 'all'
    return 'some'
  }

  const handleToggleKindSelect = (kind: string) => {
    const state = getKindSelectionState(kind)
    const mList = getKindMembers(kind)
    const nextSelection = new Set(selection)

    if (state === 'all') {
      // Deselect all
      mList.forEach((m) => nextSelection.delete(m.id))
    } else {
      // Select all
      mList.forEach((m) => nextSelection.add(m.id))
    }
    setSelection(nextSelection)
  }

  // Section level selection helpers
  const getSectionSelectionState = (secKey: string, mList: Member[]) => {
    if (mList.length === 0) return 'none'
    const selectedCount = mList.filter((m) => selection.has(m.id)).length
    if (selectedCount === 0) return 'none'
    if (selectedCount === mList.length) return 'all'
    return 'some'
  }

  const handleToggleSectionSelect = (secKey: string, mList: Member[]) => {
    const state = getSectionSelectionState(secKey, mList)
    const nextSelection = new Set(selection)

    if (state === 'all') {
      mList.forEach((m) => nextSelection.delete(m.id))
    } else {
      mList.forEach((m) => nextSelection.add(m.id))
    }
    setSelection(nextSelection)
  }

  // Section visibility helpers
  const getSectionVisibilityState = (mList: Member[]) => {
    const hiddenCount = mList.filter((m) => hiddenIds.has(m.id)).length
    if (hiddenCount === 0) return 'all'
    if (hiddenCount === mList.length) return 'none'
    return 'some'
  }

  const handleToggleSectionVisibility = (mList: Member[]) => {
    const state = getSectionVisibilityState(mList)
    mList.forEach((m) => {
      toggleMemberVisibility(m.id, state === 'none')
    })
  }

  // Section isolation helper
  const handleIsolateSection = (mList: Member[]) => {
    const ids = new Set(mList.map((m) => m.id))
    const isCurrentlyIsolated =
      isolation && isolation.ids && Array.from(isolation.ids).every((id) => ids.has(id))
    if (isCurrentlyIsolated) {
      setIsolation(null)
    } else {
      setIsolation({ ids })
    }
  }

  // Section autocomplete handler
  const handleBulkSectionSearch = async (val: string) => {
    setBulkSection(val)
    if (val.trim().length >= 1) {
      try {
        const list = await sectionsApi.search(val)
        setSuggestions(list)
        setShowSuggestions(true)
      } catch {
        // ignore
      }
    } else {
      setSuggestions([])
      setShowSuggestions(false)
    }
  }

  // Bulk edit submit
  const handleBulkUpdate = async (updateData: any) => {
    if (selection.size === 0) return
    setUpdating(true)
    try {
      await bulkUpdateMembers({
        ids: Array.from(selection),
        update: updateData,
      })
      toast.success(`Successfully updated ${selection.size} members`)
      setBulkSection('')
      setBulkStatus('')
      setShowSuggestions(false)
    } catch (err: any) {
      toast.error(err.message || 'Failed to update members')
    } finally {
      setUpdating(false)
    }
  }

  // Bulk delete submit
  const handleBulkDelete = async () => {
    if (selection.size === 0) return
    if (confirm(`Are you sure you want to delete ${selection.size} members?`)) {
      setUpdating(true)
      try {
        await bulkDeleteMembers(Array.from(selection))
        toast.success(`Deleted ${selection.size} members`)
        clearSelection()
      } catch (err: any) {
        toast.error(err.message || 'Failed to delete members')
      } finally {
        setUpdating(false)
      }
    }
  }

  const handleRowClick = (m: Member, e: React.MouseEvent) => {
    if (e.shiftKey || e.ctrlKey || e.metaKey) {
      toggleSelection(m.id)
    } else {
      setSelection(new Set([m.id]))
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        backgroundColor: '#111827',
        color: '#F1F5F9',
        fontSize: '13px',
        boxSizing: 'border-box',
      }}
    >
      {/* Active page header + Clean/Build actions */}
      {activePage && (
        <div style={{ padding: '12px 16px 0 16px' }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 10px',
              backgroundColor: '#1F2937',
              border: '1px solid rgba(59, 130, 246, 0.12)',
              borderRadius: '6px',
              marginBottom: '8px',
            }}
          >
            <span
              style={{
                fontSize: '12px',
                fontWeight: 700,
                color: '#E2E8F0',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
              title={activePage.title || undefined}
            >
              Page {(activePage.idx ?? 0) + 1}
              {activePage.title ? ` | ${activePage.title}` : ''}
            </span>
            <ChevronDown size={13} color="#64748B" style={{ flexShrink: 0, marginLeft: '6px' }} />
          </div>

          <div style={{ display: 'flex', gap: '8px', marginBottom: '8px' }}>
            <button
              onClick={onClean}
              disabled={!onClean || members.length === 0}
              title="Delete all extracted members on this page and reset it"
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                padding: '7px 0',
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.4)',
                borderRadius: '6px',
                color: members.length === 0 ? 'rgba(239,68,68,0.4)' : '#F87171',
                fontSize: '12px',
                fontWeight: 700,
                cursor: members.length === 0 ? 'not-allowed' : 'pointer',
              }}
            >
              <Trash2 size={13} />
              Clean
            </button>
            <button
              onClick={onBuild}
              disabled={!onBuild || isBuilding}
              title="Extract members from this page"
              style={{
                flex: 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
                padding: '7px 0',
                backgroundColor: 'rgba(16, 185, 129, 0.12)',
                border: '1px solid rgba(16, 185, 129, 0.5)',
                borderRadius: '6px',
                color: '#34D399',
                fontSize: '12px',
                fontWeight: 700,
                cursor: isBuilding ? 'wait' : 'pointer',
                opacity: isBuilding ? 0.7 : 1,
              }}
            >
              {isBuilding ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
              {isBuilding ? 'Building…' : 'Build'}
            </button>
          </div>
        </div>
      )}

      {/* Search Input Box */}
      <div style={{ padding: activePage ? '0 16px 8px 16px' : '12px 16px 8px 16px', position: 'relative' }}>
        <div style={{ position: 'relative' }}>
          <Search
            size={14}
            style={{
              position: 'absolute',
              left: '10px',
              top: '50%',
              transform: 'translateY(-50%)',
              color: '#64748B',
            }}
          />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search members (e.g. B_1, W12...)"
            style={{
              width: '100%',
              boxSizing: 'border-box',
              padding: '8px 12px 8px 30px',
              backgroundColor: '#1F2937',
              border: '1px solid rgba(59, 130, 246, 0.15)',
              borderRadius: '6px',
              color: '#F1F5F9',
              fontSize: '12px',
              outline: 'none',
            }}
          />
        </div>
      </div>

      {/* Explorer Toolbar Actions */}
      <div
        style={{
          padding: '0 16px 12px 16px',
          borderBottom: '1px solid rgba(59, 130, 246, 0.08)',
          display: 'flex',
          gap: '8px',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        {/* Color by selector */}
        <select
          value={layers.colorMode}
          onChange={(e) => setColorMode(e.target.value as any)}
          style={{
            padding: '4px 8px',
            backgroundColor: '#1F2937',
            border: '1px solid rgba(59, 130, 246, 0.15)',
            borderRadius: '4px',
            color: '#94A3B8',
            fontSize: '11px',
            outline: 'none',
            cursor: 'pointer',
          }}
        >
          <option value="kind">Color: Kind</option>
          <option value="status">Color: Status</option>
          <option value="confidence">Color: Confidence</option>
        </select>

        <div style={{ display: 'flex', gap: '6px' }}>
          {/* Isolate selection toggle */}
          <button
            onClick={() => {
              if (isolation && isolation.ids) {
                setIsolation(null)
              } else if (selection.size > 0) {
                setIsolation({ ids: new Set(selection) })
              } else {
                toast.info('Select members first to isolate')
              }
            }}
            title="Isolate selection"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              padding: '4px 8px',
              backgroundColor: isolation && isolation.ids ? 'rgba(59, 130, 246, 0.2)' : 'transparent',
              border: `1px solid ${
                isolation && isolation.ids ? '#3B82F6' : 'rgba(148, 163, 184, 0.2)'
              }`,
              borderRadius: '4px',
              color: isolation && isolation.ids ? '#60A5FA' : '#94A3B8',
              fontSize: '11px',
              cursor: 'pointer',
            }}
          >
            <Target size={12} />
            <span>Isolate</span>
          </button>

          {/* Show All toggler */}
          <button
            onClick={showAllMembers}
            title="Clear hidden status for all members"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '4px',
              padding: '4px 8px',
              backgroundColor: 'transparent',
              border: '1px solid rgba(148, 163, 184, 0.2)',
              borderRadius: '4px',
              color: '#94A3B8',
              fontSize: '11px',
              cursor: 'pointer',
            }}
          >
            <Eye size={12} />
            <span>Show All</span>
          </button>
        </div>
      </div>

      {/* Main Tree List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>
        {Object.keys(grouped).map((kind) => {
          const kindSections = grouped[kind]
          const kindMembersCount = getKindMembers(kind).length
          if (kindMembersCount === 0 && searchQuery) return null

          const isKindExpanded = expandedKinds[kind]
          const isKindHidden = layers.classVisibility[kind] === false

          return (
            <div key={kind} style={{ marginBottom: '12px' }}>
              {/* Kind Group Header Row -- label+count, labeled-count badge,
                  visibility check, chevron on the right (matches SteelGenie's
                  Members panel: "Columns (80) [78] ✓ >"). Bulk-select and
                  isolate are still one click away via the section rows once
                  expanded, just not cluttering the collapsed summary row. */}
              <div
                onClick={() => toggleKindCollapse(kind)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  padding: '7px 8px',
                  borderRadius: '5px',
                  backgroundColor: 'rgba(255,255,255,0.02)',
                  gap: '8px',
                  cursor: 'pointer',
                }}
              >
                <span
                  style={{
                    fontWeight: 700,
                    fontSize: '12px',
                    color: '#E2E8F0',
                    flex: 1,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {getCategoryLabel(kind)} ({kindMembersCount})
                </span>

                {kindMembersCount > 0 && (
                  <span
                    style={{
                      fontSize: '11px',
                      fontWeight: 800,
                      color: '#0F172A',
                      backgroundColor: '#F59E0B',
                      borderRadius: '10px',
                      padding: '1px 8px',
                      minWidth: '18px',
                      textAlign: 'center',
                    }}
                    title={`${getKindLabeledCount(kind)} of ${kindMembersCount} labeled`}
                  >
                    {getKindLabeledCount(kind)}
                  </span>
                )}

                {/* Visibility check -- filled/green when the whole category
                    is shown, hollow when hidden. Click without expanding. */}
                <button
                  onClick={(e) => {
                    e.stopPropagation()
                    toggleLayerVisibility(kind)
                  }}
                  style={{
                    background: 'none',
                    border: 'none',
                    padding: 0,
                    color: isKindHidden ? '#475569' : '#10B981',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                  title={isKindHidden ? 'Hidden — click to show' : 'Visible — click to hide'}
                >
                  <Check size={14} />
                </button>

                <ChevronRight
                  size={14}
                  color="#64748B"
                  style={{ transform: isKindExpanded ? 'rotate(90deg)' : 'none', transition: 'transform 0.15s' }}
                />
              </div>

              {/* Section Sub-tree */}
              {isKindExpanded && (
                <div style={{ paddingLeft: '16px', marginTop: '4px' }}>
                  {Object.keys(kindSections).map((sectionName) => {
                    const sectionMembers = kindSections[sectionName]
                    const secKey = `${kind}-${sectionName}`
                    const isSecExpanded = expandedSections[secKey]
                    const secSelectionState = getSectionSelectionState(secKey, sectionMembers)
                    const secVisibilityState = getSectionVisibilityState(sectionMembers)
                    const isSecIsolated =
                      isolation &&
                      isolation.ids &&
                      Array.from(isolation.ids).every((id) =>
                        sectionMembers.some((sm) => sm.id === id)
                      )

                    // Counts for badges
                    const totalSec = sectionMembers.length
                    const verifiedSec = sectionMembers.filter((m) => m.status === 'verified')
                      .length
                    const needReviewSec = sectionMembers.filter(
                      (m) =>
                        m.status === 'need_review' ||
                        m.section === null ||
                        (m.confidence !== null && m.confidence !== undefined && m.confidence < 0.7)
                    ).length

                    return (
                      <div key={sectionName} style={{ marginTop: '2px' }}>
                        {/* Section Header Row */}
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            padding: '3px 6px',
                            borderRadius: '3px',
                            gap: '6px',
                          }}
                        >
                          <button
                            onClick={() => toggleSectionCollapse(secKey)}
                            style={{
                              background: 'none',
                              border: 'none',
                              padding: 0,
                              color: '#475569',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            {isSecExpanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                          </button>

                          <button
                            onClick={() => handleToggleSectionSelect(secKey, sectionMembers)}
                            style={{
                              background: 'none',
                              border: 'none',
                              padding: 0,
                              color: secSelectionState !== 'none' ? '#3B82F6' : '#475569',
                              cursor: 'pointer',
                              display: 'flex',
                              alignItems: 'center',
                            }}
                          >
                            {secSelectionState === 'all' && <CheckSquare size={12} />}
                            {secSelectionState === 'some' && <MinusSquare size={12} />}
                            {secSelectionState === 'none' && <Square size={12} />}
                          </button>

                          {/* Section name & counts */}
                          <span
                            style={{
                              fontSize: '11px',
                              fontWeight: 600,
                              color: '#94A3B8',
                              flex: 1,
                              cursor: 'pointer',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                            onClick={() => toggleSectionCollapse(secKey)}
                          >
                            {sectionName} ({totalSec})
                          </span>

                          {/* Counts badges */}
                          <div style={{ display: 'flex', gap: '4px', fontSize: '9px' }}>
                            {verifiedSec > 0 && (
                              <span
                                style={{
                                  color: '#10B981',
                                  backgroundColor: 'rgba(16,185,129,0.08)',
                                  padding: '1px 3px',
                                  borderRadius: '3px',
                                }}
                              >
                                {verifiedSec}✓
                              </span>
                            )}
                            {needReviewSec > 0 && (
                              <span
                                style={{
                                  color: '#F59E0B',
                                  backgroundColor: 'rgba(245,158,11,0.08)',
                                  padding: '1px 3px',
                                  borderRadius: '3px',
                                }}
                              >
                                {needReviewSec}⚠
                              </span>
                            )}
                          </div>

                          {/* Section Visibility Eye */}
                          <button
                            onClick={() => handleToggleSectionVisibility(sectionMembers)}
                            style={{
                              background: 'none',
                              border: 'none',
                              padding: 0,
                              color: secVisibilityState === 'none' ? '#EF4444' : '#475569',
                              cursor: 'pointer',
                            }}
                            title="Toggle section visibility"
                          >
                            {secVisibilityState === 'none' ? <EyeOff size={11} /> : <Eye size={11} />}
                          </button>

                          {/* Section Isolation Target */}
                          <button
                            onClick={() => handleIsolateSection(sectionMembers)}
                            style={{
                              background: 'none',
                              border: 'none',
                              padding: 0,
                              color: isSecIsolated ? '#F59E0B' : '#475569',
                              cursor: 'pointer',
                            }}
                            title="Isolate section"
                          >
                            <Target size={11} />
                          </button>
                        </div>

                        {/* Individual Members List */}
                        {isSecExpanded && (
                          <div
                            style={{
                              paddingLeft: '22px',
                              display: 'flex',
                              flexDirection: 'column',
                              gap: '2px',
                              marginTop: '2px',
                            }}
                          >
                            {sectionMembers.map((m) => {
                              const isSelected = selection.has(m.id)
                              const isHidden = hiddenIds.has(m.id)
                              const needsReview =
                                m.status === 'need_review' ||
                                m.section === null ||
                                (m.confidence !== null &&
                                  m.confidence !== undefined &&
                                  m.confidence < 0.7)

                              return (
                                <div
                                  key={m.id}
                                  onClick={(e) => handleRowClick(m, e)}
                                  onDoubleClick={() => setZoomTarget(m.id)}
                                  style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    padding: '4px 6px',
                                    borderRadius: '4px',
                                    cursor: 'pointer',
                                    backgroundColor: isSelected
                                      ? 'rgba(59, 130, 246, 0.15)'
                                      : 'transparent',
                                    border: isSelected
                                      ? '1px solid rgba(59, 130, 246, 0.3)'
                                      : '1px solid transparent',
                                    gap: '6px',
                                    opacity: isHidden ? 0.4 : 1,
                                    transition: 'background-color 0.1s',
                                  }}
                                  onMouseEnter={(e) => {
                                    if (!isSelected)
                                      e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.02)'
                                  }}
                                  onMouseLeave={(e) => {
                                    if (!isSelected)
                                      e.currentTarget.style.backgroundColor = 'transparent'
                                  }}
                                >
                                  {/* Selection Checkbox */}
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      toggleSelection(m.id)
                                    }}
                                    style={{
                                      background: 'none',
                                      border: 'none',
                                      padding: 0,
                                      color: isSelected ? '#3B82F6' : '#475569',
                                      cursor: 'pointer',
                                      display: 'flex',
                                      alignItems: 'center',
                                    }}
                                  >
                                    {isSelected ? <CheckSquare size={11} /> : <Square size={11} />}
                                  </button>

                                  {/* Piecemark / ID Label */}
                                  <span
                                    style={{
                                      fontSize: '11px',
                                      fontFamily: 'monospace',
                                      color: isSelected ? '#60A5FA' : '#CBD5E1',
                                      flex: 1,
                                    }}
                                  >
                                    {m.piecemark || `${m.kind[0].toUpperCase()}_${m.id.substring(0, 4)}`}
                                  </span>

                                  {/* Length */}
                                  {m.length_ft !== null && (
                                    <span style={{ fontSize: '10px', color: '#64748B' }}>
                                      {m.length_ft.toFixed(1)}'
                                    </span>
                                  )}

                                  {/* Confidence */}
                                  {m.confidence !== null && m.confidence !== undefined && (
                                    <span
                                      style={{
                                        fontSize: '10px',
                                        color: m.confidence >= 0.7 ? '#10B981' : '#F59E0B',
                                      }}
                                    >
                                      {Math.round(m.confidence * 100)}%
                                    </span>
                                  )}

                                  {/* Status Icon */}
                                  <div style={{ display: 'flex', alignItems: 'center' }}>
                                    {m.status === 'verified' && (
                                      <Check size={11} style={{ color: '#10B981' }} />
                                    )}
                                    {m.status === 'rejected' && (
                                      <Trash2 size={11} style={{ color: '#EF4444' }} />
                                    )}
                                    {needsReview && m.status !== 'verified' && (
                                      <AlertTriangle size={11} style={{ color: '#F59E0B' }} />
                                    )}
                                  </div>

                                  {/* Visibility Eye */}
                                  <button
                                    onClick={(e) => {
                                      e.stopPropagation()
                                      toggleMemberVisibility(m.id)
                                    }}
                                    style={{
                                      background: 'none',
                                      border: 'none',
                                      padding: 0,
                                      color: isHidden ? '#EF4444' : '#475569',
                                      cursor: 'pointer',
                                    }}
                                  >
                                    {isHidden ? <EyeOff size={11} /> : <Eye size={11} />}
                                  </button>
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Bulk Action Drawer (Fixed Bottom) */}
      {selection.size > 0 && (
        <div
          style={{
            borderTop: '1px solid rgba(59, 130, 246, 0.2)',
            backgroundColor: '#0F172A',
            padding: '12px 14px',
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ fontSize: '11px', fontWeight: 700, color: '#94A3B8' }}>
              Selected: {selection.size} members
            </span>
            <button
              onClick={clearSelection}
              style={{
                background: 'none',
                border: 'none',
                color: '#64748B',
                cursor: 'pointer',
                fontSize: '11px',
              }}
            >
              Clear
            </button>
          </div>

          <div style={{ display: 'flex', gap: '6px', position: 'relative' }} ref={dropdownRef}>
            {/* Set Section Auto Suggest Input */}
            <div style={{ flex: 1, position: 'relative' }}>
              <input
                value={bulkSection}
                onChange={(e) => handleBulkSectionSearch(e.target.value)}
                onFocus={() => {
                  if (bulkSection.trim().length >= 1) {
                    handleBulkSectionSearch(bulkSection)
                  }
                }}
                placeholder="Bulk Section (e.g. W12X26)"
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  padding: '6px 8px',
                  backgroundColor: '#1E293B',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '4px',
                  color: '#F1F5F9',
                  fontSize: '11px',
                  outline: 'none',
                }}
              />

              {showSuggestions && suggestions.length > 0 && (
                <div
                  style={{
                    position: 'absolute',
                    bottom: '100%',
                    left: 0,
                    right: 0,
                    zIndex: 100,
                    backgroundColor: '#1E293B',
                    border: '1px solid rgba(59, 130, 246, 0.2)',
                    borderRadius: '4px',
                    maxHeight: '140px',
                    overflowY: 'auto',
                    boxShadow: '0 -4px 12px rgba(0, 0, 0, 0.5)',
                    marginBottom: '4px',
                  }}
                >
                  {suggestions.map((s) => (
                    <div
                      key={s.designation}
                      onClick={() => {
                        setBulkSection(s.designation)
                        setShowSuggestions(false)
                        handleBulkUpdate({ section: s.designation })
                      }}
                      style={{
                        padding: '6px 10px',
                        cursor: 'pointer',
                        fontSize: '11px',
                        color: '#F1F5F9',
                        borderBottom: '1px solid rgba(59, 130, 246, 0.05)',
                        transition: 'background-color 0.2s',
                      }}
                      onMouseEnter={(e) =>
                        (e.currentTarget.style.backgroundColor = 'rgba(59, 130, 246, 0.15)')
                      }
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                    >
                      <div style={{ fontWeight: 600 }}>{s.designation}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Set Status Dropdown */}
            <select
              value={bulkStatus}
              onChange={(e) => {
                setBulkStatus(e.target.value)
                handleBulkUpdate({ status: e.target.value })
              }}
              style={{
                width: '100px',
                padding: '6px 8px',
                backgroundColor: '#1E293B',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                borderRadius: '4px',
                color: '#F1F5F9',
                fontSize: '11px',
                outline: 'none',
                cursor: 'pointer',
              }}
            >
              <option value="">Status ▾</option>
              <option value="active">Active</option>
              <option value="need_review">Need Review</option>
              <option value="verified">Verified</option>
              <option value="rejected">Rejected</option>
              <option value="excluded">Excluded</option>
            </select>
          </div>

          <div style={{ display: 'flex', gap: '6px' }}>
            {/* Bulk Verify Button */}
            <button
              onClick={() => handleBulkUpdate({ status: 'verified' })}
              disabled={updating}
              style={{
                flex: 1,
                padding: '6px 10px',
                backgroundColor: '#10B981',
                border: 'none',
                borderRadius: '4px',
                color: '#FFFFFF',
                fontWeight: 600,
                fontSize: '11px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '4px',
              }}
            >
              <Check size={12} />
              <span>Verify ✓</span>
            </button>

            {/* Bulk Delete Button */}
            <button
              onClick={handleBulkDelete}
              disabled={updating}
              style={{
                padding: '6px 10px',
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '4px',
                color: '#EF4444',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              title="Delete selected members"
            >
              <Trash2 size={12} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
