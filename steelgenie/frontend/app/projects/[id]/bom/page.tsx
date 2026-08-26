'use client'

import React, { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useParams } from 'next/navigation'
import { bomApi, buildApi, jobsApi, drawingsApi } from '../../../../lib/api'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'
import { useWorkspace } from '../../../../features/workspace/hooks/useWorkspace'
import { Spinner } from '../../../../components/ui/Spinner'
import { Download, RefreshCw, Search, SlidersHorizontal, X, Columns, Upload, ChevronDown, ChevronUp } from 'lucide-react'
import { toast } from 'sonner'

interface BomItem {
  id: string
  piecemark: string | null
  category: string | null
  qty: number
  section_type: string | null
  section: string | null
  length_in: number | null
  grade: string | null
  labor_code: string | null
  weight_lbs: number | null
  camber: number
  cope: number
  holes: number
  weld_studs: number
  status: string | null
  sequence: number | null
  is_main: boolean
  sheet: string | null
  comment: string | null
  dcr_left: number | null
  dcr_right: number | null
}

interface BomSummary {
  total_items: number
  total_weight_lbs: number
  total_weight_tons: number
  by_category: Record<string, number>
}

interface BomFacets {
  category: string[]
  piecemark: string[]
  section_type: string[]
  section: string[]
  grade: string[]
  labor_code: string[]
  status: string[]
  sequence: string[]
  sheet: string[]
}

const EMPTY_FACETS: BomFacets = {
  category: [], piecemark: [], section_type: [], section: [], grade: [], labor_code: [], status: [], sequence: [], sheet: [],
}

type Filters = {
  category: string
  section_type: string
  section: string
  grade: string
  labor_code: string
  status: string
  sequence: string
  is_main: string // '', 'true', 'false'
  sheet: string
}

const EMPTY_FILTERS: Filters = {
  category: '', section_type: '', section: '', grade: '', labor_code: '', status: '', sequence: '', is_main: '', sheet: '',
}

function FilterSelect({ label, value, options, onChange, theme = 'dark' }: { label: string; value: string; options: string[]; onChange: (v: string) => void; theme?: 'light' | 'dark' }) {
  const isLight = theme === 'light'
  return (
    <div style={{ marginBottom: '14px' }}>
      <label style={{ display: 'block', fontSize: '11px', color: '#64748B', marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '0.3px' }}>
        {label}
      </label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: '100%', padding: '7px 10px',
          backgroundColor: isLight ? '#F8FAFC' : '#1F2937',
          border: isLight ? '1px solid #E2E8F0' : '1px solid rgba(59, 130, 246, 0.15)',
          borderRadius: '6px',
          color: isLight ? '#334155' : '#F1F5F9',
          fontSize: '12px', outline: 'none',
        }}
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  )
}

function ToggleSwitch({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        onChange(!checked)
      }}
      style={{
        width: '38px',
        height: '20px',
        borderRadius: '10px',
        backgroundColor: checked ? '#00A389' : '#94A3B8',
        position: 'relative',
        cursor: 'pointer',
        border: 'none',
        outline: 'none',
        transition: 'background-color 0.2s ease',
        padding: 0,
        flexShrink: 0,
      }}
    >
      <div
        style={{
          width: '14px',
          height: '14px',
          borderRadius: '50%',
          backgroundColor: '#FFFFFF',
          position: 'absolute',
          top: '3px',
          left: checked ? '21px' : '3px',
          transition: 'left 0.2s ease',
        }}
      />
    </button>
  )
}

const cleanSheetName = (sheetStr: string | null | undefined): string => {
  if (!sheetStr) return '-'
  const match = sheetStr.match(/Page\s+\d+/i)
  if (match) return match[0]
  return sheetStr.replace(/^[^-—]+[-—]\s*/, '')
}

const formatStatus = (status: string | null) => {
  if (!status) return 'Not Started'
  return status
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

export default function BomPage() {
  const params = useParams()
  const projectId = params?.id as string

  const { currentPageId } = useWorkspaceStore()
  const { drawings, pages } = useWorkspace(projectId)

  const activePage = useMemo(() => pages.find((p: any) => p.id === currentPageId), [pages, currentPageId])
  const activeDrawing = useMemo(() => activePage ? drawings.find((d: any) => d.id === activePage.drawing_id) : null, [drawings, activePage])
  
  const activeSheetName = useMemo(() => {
    if (!activePage) return ''
    return `${activeDrawing?.filename || 'Drawing'} — Page ${activePage.idx + 1}`
  }, [activePage, activeDrawing])

  const pageDisplayMap = useMemo(() => {
    const map: Record<string, string> = {}
    pages.forEach((p: any, index: number) => {
      const displayNum = `Page ${index + 1}`
      map[p.id] = displayNum
      map[`Page ${p.idx + 1}`] = displayNum
      map[`Page ${p.idx + 1}`.toLowerCase()] = displayNum
      const drawing = drawings.find((d: any) => d.id === p.drawing_id)
      const fullName = `${drawing?.filename || 'Drawing'} — Page ${p.idx + 1}`
      map[fullName] = displayNum
      map[p.drawing_id + '_' + p.idx] = displayNum
    })
    return map
  }, [pages, drawings])

  const getSidebarPageName = useCallback((sheetStr: string | null | undefined): string => {
    if (!sheetStr) return '-'
    if (pageDisplayMap[sheetStr]) return pageDisplayMap[sheetStr]
    const m = sheetStr.match(/Page\s+(\d+)/i)
    if (m) {
      const rawIdx = parseInt(m[1], 10)
      const pageEntry = pages.find((p: any) => p.idx + 1 === rawIdx)
      if (pageEntry) {
        const pIdx = pages.indexOf(pageEntry)
        if (pIdx >= 0) return `Page ${pIdx + 1}`
      }
      return m[0]
    }
    return sheetStr.replace(/^[^-—]+[-—]\s*/, '')
  }, [pageDisplayMap, pages])

  const [items, setItems] = useState<BomItem[]>([])
  const [summary, setSummary] = useState<BomSummary | null>(null)
  const [facets, setFacets] = useState<BomFacets>(EMPTY_FACETS)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [buildProgress, setBuildProgress] = useState(0)
  const [buildMsg, setBuildMsg] = useState('')
  const [buildWarnings, setBuildWarnings] = useState<string[]>([])
  const [showWarnings, setShowWarnings] = useState(true)
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS)
  const [search, setSearch] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const [isStale, setIsStale] = useState(false)

  const [showFieldsDropdown, setShowFieldsDropdown] = useState(false)
  const [showExportDropdown, setShowExportDropdown] = useState(false)

  const fieldsRef = useRef<HTMLDivElement>(null)
  const exportRef = useRef<HTMLDivElement>(null)

  const [lastPageId, setLastPageId] = useState<string | null>(null)

  const [visibleFields, setVisibleFields] = useState<Record<string, boolean>>({
    is_main: true,
    category: true,
    piecemark: true,
    sub_number: false,
    qty: true,
    section_type: true,
    section: true,
    length_in: true,
    grade: true,
    labor_code: true,
    weight_lbs: true,
    camber: true,
    cope: true,
    holes: true,
    bolts: false,
    weld_studs: false,
    status: true,
    sequence: true,
    comment: true,
    sheet: true,
    dcr_left: true,
    dcr_right: true,
  })



  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (fieldsRef.current && !fieldsRef.current.contains(event.target as Node)) {
        setShowFieldsDropdown(false)
      }
      if (exportRef.current && !exportRef.current.contains(event.target as Node)) {
        setShowExportDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const setFilter = (key: keyof Filters, value: string) => setFilters((f) => ({ ...f, [key]: value }))

  const checkStale = useCallback(async () => {
    try {
      const latest = await buildApi.latest(projectId)
      const builtAt = latest?.job?.finished_at || latest?.job?.updated_at
      if (!builtAt) {
        setIsStale(false)
        return
      }
      const builtMs = new Date(builtAt).getTime()
      const drawings = await drawingsApi.list(projectId)
      const pagesLists = await Promise.all((drawings || []).map((d: any) => drawingsApi.listPages(d.id)))
      const anyNewer = pagesLists.flat().some((p: any) => p?.updated_at && new Date(p.updated_at).getTime() > builtMs)
      setIsStale(anyNewer)
    } catch {
      setIsStale(false)
    }
  }, [projectId])

  const loadBom = useCallback(async () => {
    setLoading(true)
    try {
      const query: Record<string, any> = { limit: 10000 }
      if (filters.category) query.category = filters.category
      if (filters.section_type) query.section_type = filters.section_type
      if (filters.section) query.section = filters.section
      if (filters.grade) query.grade = filters.grade
      if (filters.labor_code) query.labor_code = filters.labor_code
      if (filters.status) query.status = filters.status
      if (filters.sequence) query.sequence = filters.sequence
      if (filters.is_main) query.is_main = filters.is_main
      if (filters.sheet) query.sheet = filters.sheet
      if (search) query.search = search

      const summaryQuery: Record<string, any> = {}
      if (filters.sheet) summaryQuery.sheet = filters.sheet

      const [dataRes, sumRes, facetRes] = await Promise.allSettled([
        bomApi.list(projectId, query),
        bomApi.summary(projectId, summaryQuery),
        bomApi.facets(projectId),
      ])

      if (dataRes.status === 'fulfilled') {
        setItems(dataRes.value)
      } else {
        setItems([])
        console.error('BOM list failed:', dataRes.reason)
      }
      if (sumRes.status === 'fulfilled') {
        setSummary(sumRes.value)
      } else {
        console.error('BOM summary failed:', sumRes.reason)
      }
      if (facetRes.status === 'fulfilled') {
        setFacets(facetRes.value)
      } else {
        console.error('BOM facets failed:', facetRes.reason)
      }

      if (dataRes.status === 'rejected' && sumRes.status === 'rejected' && facetRes.status === 'rejected') {
        toast.error('Failed to load Bill of Materials — is the backend running the latest code? Try restarting it.')
      } else if (facetRes.status === 'rejected') {
        toast.error('Filters unavailable (backend may need a restart to pick up the /bom/facets endpoint) — BOM rows still loaded.')
      }
    } catch (err: any) {
      toast.error(err?.message || 'Failed to load Bill of Materials')
    } finally {
      setLoading(false)
    }
  }, [projectId, filters, search])

  useEffect(() => {
    if (projectId) loadBom()
  }, [projectId, loadBom])

  useEffect(() => {
    if (projectId) checkStale()
  }, [projectId, checkStale])

  const handleGenerate = async () => {
    setGenerating(true)
    setBuildProgress(10)
    setBuildMsg('Starting project build…')
    setBuildWarnings([])
    try {
      const { job_id } = await buildApi.trigger(projectId)
      for (;;) {
        const job = await jobsApi.get(job_id)
        const pct = job.progress ?? (job.status === 'done' ? 100 : 25)
        setBuildProgress(pct)
        setBuildMsg(job.message || 'Building…')
        if (job.status === 'done') {
          setBuildProgress(100)
          const warnings: string[] = job.result?.warnings || []
          setBuildWarnings(warnings)
          setShowWarnings(true)
          if (warnings.length > 0) {
            toast.warning(`${job.message || 'Build complete'} — ${warnings.length} warning(s).`)
          } else {
            toast.success(job.message || 'Build complete')
          }
          break
        }
        if (job.status === 'failed') {
          throw new Error(job.error || 'Build failed')
        }
        await new Promise((r) => setTimeout(r, 400))
      }
      await loadBom()
      await checkStale()
    } catch (err: any) {
      toast.error(err.message || 'Build failed')
    } finally {
      setGenerating(false)
      setBuildMsg('')
      setBuildProgress(0)
    }
  }

  const handleDownloadCsv = () => window.open(bomApi.getExportUrl(projectId), '_blank')
  const handleDownloadKiss = () => window.open(bomApi.getKissExportUrl(projectId), '_blank')
  const handleDownloadEpm = () => window.open(bomApi.getEpmExportUrl(projectId), '_blank')

  const getFormatLength = useCallback((lenIn: number | null) => {
    if (lenIn === null || lenIn === undefined) return '-'
    const feet = Math.floor(lenIn / 12)
    const remainingInches = lenIn % 12
    const wholeInches = Math.floor(remainingInches)
    const fractionalPart = remainingInches - wholeInches

    let fractionStr = ''
    const sixteenths = Math.round(fractionalPart * 16)
    if (sixteenths > 0 && sixteenths < 16) {
      const gcd = (a: number, b: number): number => (b === 0 ? a : gcd(b, a % b))
      const common = gcd(sixteenths, 16)
      const num = sixteenths / common
      const den = 16 / common
      fractionStr = ` ${num}/${den}`
    } else if (sixteenths === 16) {
      return `${feet}'-${wholeInches + 1}"`
    }

    if (feet === 0 && wholeInches === 0 && !fractionStr) return '0"'
    return `${feet}'-${wholeInches}${fractionStr}"`
  }, [])

  const activeFilterCount = useMemo(
    () => Object.values(filters).filter(Boolean).length + (search ? 1 : 0),
    [filters, search]
  )

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS)
    setSearch('')
  }

  const handleHideAll = () => {
    setVisibleFields((prev) => {
      const next = { ...prev }
      Object.keys(next).forEach((key) => {
        next[key] = false
      })
      return next
    })
  }

  const handleShowAll = () => {
    setVisibleFields((prev) => {
      const next = { ...prev }
      Object.keys(next).forEach((key) => {
        next[key] = true
      })
      return next
    })
  }

  const accessoryMap = useMemo(() => {
    const map: Record<string, { bolts: number; weld_studs: number }> = {}
    items.forEach(item => {
      if (!item.piecemark) return
      if (!map[item.piecemark]) {
        map[item.piecemark] = { bolts: 0, weld_studs: 0 }
      }
      if (item.category === 'Bolts') {
        map[item.piecemark].bolts += item.qty || 0
      }
      if (item.category === 'Weld Studs') {
        map[item.piecemark].weld_studs += item.weld_studs || item.qty || 0
      }
    })
    return map
  }, [items])

  const columns = useMemo(() => [
    { id: 'is_main', label: 'MAIN', dropdownLabel: 'Main', render: (item: BomItem) => item.is_main ? '1' : '0' },
    { id: 'category', label: 'CATEGORY', dropdownLabel: 'Category', render: (item: BomItem) => item.category || '-' },
    { id: 'piecemark', label: 'PIECEMARK', dropdownLabel: 'Piecemark', render: (item: BomItem) => item.piecemark || '-', isPiecemark: true },
    { id: 'sub_number', label: 'SUB NUMBER', dropdownLabel: 'Sub Number', render: (item: BomItem) => '-' },
    { id: 'qty', label: 'QTY', dropdownLabel: 'Qty', render: (item: BomItem) => item.qty },
    { id: 'section_type', label: 'SECTION TYPE', dropdownLabel: 'Section Type', render: (item: BomItem) => item.section_type || '-' },
    { id: 'section', label: 'SECTION', dropdownLabel: 'Section', render: (item: BomItem) => item.section || '-', isSection: true },
    { id: 'length_in', label: 'LENGTH', dropdownLabel: 'Length', render: (item: BomItem) => getFormatLength(item.length_in) },
    { id: 'grade', label: 'GRADE', dropdownLabel: 'Grade', render: (item: BomItem) => item.grade || '-' },
    { id: 'labor_code', label: 'LABOR CODE', dropdownLabel: 'Labor Code', render: (item: BomItem) => item.labor_code || '-' },
    { id: 'weight_lbs', label: 'WEIGHT-LBS', dropdownLabel: 'Weight', render: (item: BomItem) => item.weight_lbs !== null ? item.weight_lbs.toLocaleString() : '-' },
    { id: 'camber', label: 'CAMBER', dropdownLabel: 'Camber', render: (item: BomItem) => item.camber || 0 },
    { id: 'cope', label: 'COPE', dropdownLabel: 'Cope', render: (item: BomItem) => item.cope || 0 },
    { id: 'holes', label: 'HOLE', dropdownLabel: 'Hole', render: (item: BomItem) => item.holes || 0 },
    { id: 'bolts', label: 'BOLTS', dropdownLabel: 'Bolts', render: (item: BomItem) => {
      if (item.piecemark && accessoryMap[item.piecemark]) {
        return accessoryMap[item.piecemark].bolts
      }
      return 0
    } },
    { id: 'weld_studs', label: 'WELD STUD', dropdownLabel: 'Weld Stud', render: (item: BomItem) => {
      if (item.piecemark && accessoryMap[item.piecemark]) {
        return accessoryMap[item.piecemark].weld_studs || item.weld_studs || 0
      }
      return item.weld_studs || 0
    } },
    { id: 'status', label: 'STATUS', dropdownLabel: 'Status', render: (item: BomItem) => formatStatus(item.status) },
    { id: 'sequence', label: 'SEQUENCE', dropdownLabel: 'Sequence', render: (item: BomItem) => item.sequence ?? '-' },
    { id: 'comment', label: 'COMMENT', dropdownLabel: 'Comment', render: (item: BomItem) => item.comment || '-' },
    { id: 'sheet', label: 'SHEET', dropdownLabel: 'Sheet', render: (item: BomItem) => getSidebarPageName(item.sheet) },
    { id: 'dcr_left', label: 'DCR LEFT', dropdownLabel: 'DCR Left', render: (item: BomItem) => item.dcr_left ?? '-' },
    { id: 'dcr_right', label: 'DCR RIGHT', dropdownLabel: 'DCR Right', render: (item: BomItem) => item.dcr_right ?? '-' },
  ], [getFormatLength, accessoryMap, getSidebarPageName])

  const activeColumns = useMemo(() => {
    return columns.filter((col) => visibleFields[col.id])
  }, [columns, visibleFields])

  const filteredItems = useMemo(() => {
    return items.filter(item => {
      if (filters.category) {
        return (item.category || '').toLowerCase() === filters.category.toLowerCase()
      }
      return true
    })
  }, [items, filters.category])

  const groupedItems = useMemo(() => {
    const groups: Record<string, { items: BomItem[]; totalWeight: number }> = {}
    let grandTotalWeight = 0

    filteredItems.forEach(item => {
      const sheetName = getSidebarPageName(item.sheet)
      if (!groups[sheetName]) {
        groups[sheetName] = { items: [], totalWeight: 0 }
      }
      groups[sheetName].items.push(item)
      const weight = item.weight_lbs || 0
      groups[sheetName].totalWeight += weight
      grandTotalWeight += weight
    })

    // Sort sheets by numeric page order (Page 1, Page 2, Page 3, ...)
    const sortedSheets = Object.keys(groups).sort((a, b) => {
      const numA = parseInt(a.replace(/\D/g, ''), 10) || 0
      const numB = parseInt(b.replace(/\D/g, ''), 10) || 0
      return numA - numB
    })

    return {
      groups: sortedSheets.map(sheet => ({
        sheet,
        items: groups[sheet].items,
        totalWeight: groups[sheet].totalWeight
      })),
      grandTotalWeight
    }
  }, [filteredItems, getSidebarPageName])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box', overflow: 'hidden', backgroundColor: '#F8FAFC' }}>
      <style dangerouslySetInnerHTML={{ __html: `
        .custom-fields-scroll::-webkit-scrollbar {
          width: 6px;
        }
        .custom-fields-scroll::-webkit-scrollbar-track {
          background: #f1f5f9;
        }
        .custom-fields-scroll::-webkit-scrollbar-thumb {
          background: #cbd5e1;
          border-radius: 3px;
        }
        .custom-fields-scroll::-webkit-scrollbar-thumb:hover {
          background: #94a3b8;
        }
      `}} />

      {/* Top action row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center' }}>
            <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#0F172A' }}>Bill of Materials</h1>
            <span
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                minWidth: '24px',
                height: '24px',
                borderRadius: '12px',
                backgroundColor: '#7B99B9',
                color: '#FFFFFF',
                fontSize: '13px',
                fontWeight: 600,
                marginLeft: '8px',
                padding: '0 6px',
              }}
            >
              {filteredItems.length}
            </span>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
            Piecemarked takeoff — main members plus connection material, generated by the build engine
          </p>
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button
            onClick={handleGenerate}
            disabled={generating}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px',
              backgroundColor: '#FFFFFF',
              border: '1px solid #CBD5E1', borderRadius: '6px',
              color: '#3B82F6', fontSize: '13px', fontWeight: 600,
              cursor: generating ? 'not-allowed' : 'pointer',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={(e) => {
              if (!generating) e.currentTarget.style.backgroundColor = '#F8FAFC'
            }}
            onMouseLeave={(e) => {
              if (!generating) e.currentTarget.style.backgroundColor = '#FFFFFF'
            }}
          >
            <RefreshCw size={14} className={generating ? 'animate-spin' : ''} />
            {generating ? buildMsg || 'Building...' : 'Build Project'}
          </button>

          <div ref={fieldsRef} style={{ position: 'relative' }}>
            <button
              onClick={() => {
                setShowFieldsDropdown(!showFieldsDropdown)
                setShowExportDropdown(false)
              }}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px',
                backgroundColor: '#FFFFFF',
                border: showFieldsDropdown ? '1.5px solid #000000' : '1px solid #CBD5E1',
                borderRadius: '6px',
                color: '#334155', fontSize: '13px', fontWeight: 600,
                cursor: 'pointer',
                boxShadow: showFieldsDropdown ? '0 0 0 1px #000000' : 'none',
                transition: 'all 0.15s ease',
              }}
            >
              <Columns size={14} />
              Fields
            </button>
            {showFieldsDropdown && (
              <div
                style={{
                  position: 'absolute',
                  top: 'calc(100% + 6px)',
                  right: 0,
                  width: '280px',
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #E2E8F0',
                  borderRadius: '8px',
                  boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
                  padding: '14px 16px',
                  zIndex: 100,
                  display: 'flex',
                  flexDirection: 'column',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                  <span style={{ fontSize: '13px', fontWeight: 600, color: '#334155' }}>Field Visibility</span>
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button
                      onClick={handleHideAll}
                      style={{ background: 'none', border: 'none', color: '#94A3B8', fontSize: '12px', fontWeight: 500, cursor: 'pointer', padding: 0 }}
                    >
                      Hide All
                    </button>
                    <span style={{ color: '#E2E8F0', fontSize: '12px' }}>|</span>
                    <button
                      onClick={handleShowAll}
                      style={{ background: 'none', border: 'none', color: '#3B82F6', fontSize: '12px', fontWeight: 500, cursor: 'pointer', padding: 0 }}
                    >
                      Show All
                    </button>
                  </div>
                </div>
                <div
                  style={{
                    maxHeight: '320px',
                    overflowY: 'auto',
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '4px',
                    paddingRight: '4px',
                  }}
                  className="custom-fields-scroll"
                >
                  {columns.map((col) => (
                    <div
                      key={col.id}
                      onClick={() => setVisibleFields((prev) => ({ ...prev, [col.id]: !prev[col.id] }))}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '6px 0',
                        cursor: 'pointer',
                      }}
                    >
                      <span style={{ fontSize: '13px', color: '#475569', userSelect: 'none' }}>
                        {col.dropdownLabel}
                      </span>
                      <ToggleSwitch
                        checked={visibleFields[col.id]}
                        onChange={(val) => setVisibleFields((prev) => ({ ...prev, [col.id]: val }))}
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          <div ref={exportRef} style={{ position: 'relative' }}>
            <button
              onClick={() => {
                setShowExportDropdown(!showExportDropdown)
                setShowFieldsDropdown(false)
              }}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px', padding: '8px 14px',
                backgroundColor: '#FFFFFF',
                border: showExportDropdown ? '1.5px solid #000000' : '1px solid #CBD5E1',
                borderRadius: '6px',
                color: '#334155', fontSize: '13px', fontWeight: 600,
                cursor: 'pointer',
                boxShadow: showExportDropdown ? '0 0 0 1px #000000' : 'none',
                transition: 'all 0.15s ease',
              }}
            >
              <Upload size={14} />
              Export
              {showExportDropdown ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {showExportDropdown && (
              <div
                style={{
                  position: 'absolute',
                  top: 'calc(100% + 6px)',
                  left: 0,
                  width: '190px',
                  backgroundColor: '#FFFFFF',
                  border: '1px solid #E2E8F0',
                  borderRadius: '8px',
                  boxShadow: '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
                  padding: '4px 0',
                  zIndex: 100,
                  display: 'flex',
                  flexDirection: 'column',
                }}
              >
                <button
                  onClick={() => {
                    handleDownloadEpm()
                    setShowExportDropdown(false)
                  }}
                  disabled={filteredItems.length === 0}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px',
                    backgroundColor: 'transparent', border: 'none', outline: 'none',
                    color: filteredItems.length === 0 ? '#94A3B8' : '#334155', fontSize: '13px', fontWeight: 500,
                    cursor: filteredItems.length === 0 ? 'not-allowed' : 'pointer', textAlign: 'left',
                    transition: 'background-color 0.2s',
                  }}
                  onMouseEnter={(e) => {
                    if (filteredItems.length > 0) e.currentTarget.style.backgroundColor = '#F1F5F9'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent'
                  }}
                >
                  <Upload size={14} />
                  Tekla EPM Excel
                </button>
                <button
                  onClick={() => {
                    handleDownloadCsv()
                    setShowExportDropdown(false)
                  }}
                  disabled={filteredItems.length === 0}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px',
                    backgroundColor: 'transparent', border: 'none', outline: 'none',
                    color: filteredItems.length === 0 ? '#94A3B8' : '#334155', fontSize: '13px', fontWeight: 500,
                    cursor: filteredItems.length === 0 ? 'not-allowed' : 'pointer', textAlign: 'left',
                    transition: 'background-color 0.2s',
                  }}
                  onMouseEnter={(e) => {
                    if (filteredItems.length > 0) e.currentTarget.style.backgroundColor = '#F1F5F9'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent'
                  }}
                >
                  <Upload size={14} />
                  Export Bill of Material
                </button>
                <button
                  onClick={() => {
                    handleDownloadKiss()
                    setShowExportDropdown(false)
                  }}
                  disabled={filteredItems.length === 0}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px',
                    backgroundColor: 'transparent', border: 'none', outline: 'none',
                    color: filteredItems.length === 0 ? '#94A3B8' : '#334155', fontSize: '13px', fontWeight: 500,
                    cursor: filteredItems.length === 0 ? 'not-allowed' : 'pointer', textAlign: 'left',
                    transition: 'background-color 0.2s',
                  }}
                  onMouseEnter={(e) => {
                    if (filteredItems.length > 0) e.currentTarget.style.backgroundColor = '#F1F5F9'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent'
                  }}
                >
                  <Upload size={14} />
                  Export KISS File
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Stale-build banner */}
      {isStale && (
        <div style={{ marginBottom: '16px', backgroundColor: '#EFF6FF', border: '1px solid #BFDBFE', borderRadius: '8px', padding: '12px 16px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px' }}>
          <span style={{ fontSize: '12px', color: '#1E40AF', fontWeight: 500 }}>
            One or more drawings were extracted after the last build — this BOM doesn't include that yet.
          </span>
          <button
            onClick={handleGenerate}
            disabled={generating}
            style={{ background: 'none', border: 'none', color: '#2563EB', fontSize: '12px', fontWeight: 700, cursor: generating ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap' }}
          >
            Rebuild now
          </button>
        </div>
      )}

      {/* Build warnings */}
      {buildWarnings.length > 0 && showWarnings && (
        <div style={{ marginBottom: '16px', backgroundColor: '#FFFBEB', border: '1px solid #FDE68A', borderRadius: '8px', padding: '12px 16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
            <div style={{ fontSize: '12px', fontWeight: 700, color: '#B45309', marginBottom: '6px' }}>
              {buildWarnings.length} item(s) were left out of this BOM
            </div>
            <button onClick={() => setShowWarnings(false)} style={{ background: 'none', border: 'none', color: '#B45309', cursor: 'pointer', padding: 0 }}>
              <X size={13} />
            </button>
          </div>
          <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '12px', color: '#D97706', lineHeight: 1.6 }}>
            {buildWarnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Live Build Progress Bar Card */}
      {generating && (
        <div style={{
          marginBottom: '20px',
          padding: '16px 20px',
          backgroundColor: '#0F172A',
          border: '1px solid #3B82F6',
          borderRadius: '8px',
          boxShadow: '0 4px 20px rgba(59, 130, 246, 0.2)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <RefreshCw size={16} className="animate-spin" color="#38BDF8" />
              <span style={{ fontSize: '14px', fontWeight: 600, color: '#F8FAFC' }}>
                {buildMsg || 'Building Project Takeoff & Calculating Tonnage...'}
              </span>
            </div>
            <span style={{ fontSize: '15px', fontWeight: 700, color: '#38BDF8' }}>
              {buildProgress}%
            </span>
          </div>
          <div style={{
            width: '100%',
            height: '8px',
            backgroundColor: '#1E293B',
            borderRadius: '4px',
            overflow: 'hidden',
          }}>
            <div style={{
              width: `${Math.max(5, buildProgress)}%`,
              height: '100%',
              backgroundColor: '#3B82F6',
              borderRadius: '4px',
              transition: 'width 0.3s ease',
              backgroundImage: 'linear-gradient(90deg, #3B82F6, #60A5FA)',
            }} />
          </div>
        </div>
      )}

      {/* Summary dashboard */}
      {summary && (
        <div style={{ display: 'flex', gap: '16px', marginBottom: '16px', flexWrap: 'wrap' }}>
          {[
            { label: 'Total Weight (tons)', value: (groupedItems.grandTotalWeight / 2000).toFixed(2) },
            { label: 'BOM Items', value: filteredItems.length },
            { label: 'Beams', value: filteredItems.filter(item => item.category?.toLowerCase() === 'beams').length },
            { label: 'Columns', value: filteredItems.filter(item => item.category?.toLowerCase() === 'columns').length },
          ].map((stat, i) => (
            <div key={i} style={{ flex: '1 1 160px', backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '8px', padding: '12px 16px', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
              <div style={{ fontSize: '18px', fontWeight: 700, color: '#0F172A' }}>{stat.value}</div>
              <div style={{ fontSize: '10px', color: '#64748B', marginTop: '2px', textTransform: 'uppercase', letterSpacing: '0.4px' }}>{stat.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Body: filter sidebar + grid */}
      <div style={{ flex: 1, display: 'flex', gap: '16px', minHeight: 0 }}>
        {showFilters && (
          <div style={{ width: '220px', flexShrink: 0, backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '8px', padding: '16px', overflowY: 'auto' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
              <span style={{ fontSize: '12px', fontWeight: 700, color: '#0F172A', textTransform: 'uppercase', letterSpacing: '0.4px' }}>Filters</span>
              {activeFilterCount > 0 && (
                <button onClick={clearFilters} style={{ background: 'none', border: 'none', color: '#3B82F6', fontSize: '11px', cursor: 'pointer', padding: 0 }}>
                  Clear ({activeFilterCount})
                </button>
              )}
            </div>

            <div style={{ position: 'relative', marginBottom: '16px' }}>
              <Search size={13} style={{ position: 'absolute', left: '10px', top: '9px', color: '#94A3B8' }} />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search piecemark…"
                style={{
                  width: '100%', boxSizing: 'border-box', padding: '7px 10px 7px 30px', backgroundColor: '#F8FAFC',
                  border: '1px solid #E2E8F0', borderRadius: '6px', color: '#0F172A', fontSize: '12px', outline: 'none',
                }}
              />
            </div>

            <FilterSelect label="Drawing / Sheet" value={filters.sheet} options={facets.sheet} onChange={(v) => setFilter('sheet', v)} theme="light" />
            <FilterSelect label="Category" value={filters.category} options={facets.category} onChange={(v) => setFilter('category', v)} theme="light" />
            <FilterSelect label="Section Type" value={filters.section_type} options={facets.section_type} onChange={(v) => setFilter('section_type', v)} theme="light" />
            <FilterSelect label="Section" value={filters.section} options={facets.section} onChange={(v) => setFilter('section', v)} theme="light" />
            <FilterSelect label="Grade" value={filters.grade} options={facets.grade} onChange={(v) => setFilter('grade', v)} theme="light" />
            <FilterSelect label="Labor Code" value={filters.labor_code} options={facets.labor_code} onChange={(v) => setFilter('labor_code', v)} theme="light" />
            <FilterSelect label="Status" value={filters.status} options={facets.status} onChange={(v) => setFilter('status', v)} theme="light" />
            <FilterSelect label="Sequence" value={filters.sequence} options={facets.sequence} onChange={(v) => setFilter('sequence', v)} theme="light" />
            <FilterSelect label="Main / Accessory" value={filters.is_main} options={['true', 'false']} onChange={(v) => setFilter('is_main', v)} theme="light" />
          </div>
        )}

        <div style={{ flex: 1, backgroundColor: '#FFFFFF', border: '1px solid #E2E8F0', borderRadius: '8px', overflow: 'hidden', display: 'flex', flexDirection: 'column', minWidth: 0, boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
          <div style={{ padding: '10px 16px', borderBottom: '1px solid #E2E8F0', display: 'flex', alignItems: 'center', gap: '10px', backgroundColor: '#FFFFFF' }}>
            <button
              onClick={() => setShowFilters((s) => !s)}
              style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'none', border: 'none', color: '#64748B', fontSize: '12px', cursor: 'pointer', padding: '4px 6px' }}
            >
              <SlidersHorizontal size={13} /> {showFilters ? 'Hide filters' : 'Show filters'}
            </button>
            <span style={{ fontSize: '12px', color: '#94A3B8' }}>Showing {filteredItems.length} item{filteredItems.length === 1 ? '' : 's'}</span>
          </div>

          <div style={{ flex: 1, overflow: 'auto' }}>
            {loading ? (
              <div style={{ display: 'flex', height: '200px', alignItems: 'center', justifyContent: 'center' }}>
                <Spinner size="md" />
              </div>
            ) : filteredItems.length === 0 ? (
              <div style={{ display: 'flex', height: '200px', alignItems: 'center', justifyContent: 'center', color: '#64748B', fontSize: '13px', flexDirection: 'column', gap: '8px' }}>
                <span>No BOM rows match the current filters.</span>
                <span style={{ fontSize: '12px' }}>
                  {activeFilterCount > 0 ? (
                    <button onClick={clearFilters} style={{ color: '#3B82F6', background: 'none', border: 'none', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                      <X size={11} /> Clear filters
                    </button>
                  ) : (
                    'Click "Build Project" above to design connections and generate the BOM.'
                  )}
                </span>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', padding: '16px', gap: '28px' }}>
                {groupedItems.groups.map(group => (
                  <div key={group.sheet} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: '#F8FAFC', padding: '10px 16px', borderRadius: '8px', border: '1px solid #E2E8F0' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <span style={{ fontSize: '14px', fontWeight: 700, color: '#0F172A' }}>
                          📄 {group.sheet}
                        </span>
                        <span style={{ fontSize: '12px', color: '#64748B', backgroundColor: '#E2E8F0', padding: '2px 8px', borderRadius: '10px', fontWeight: 600 }}>
                          {group.items.length} items
                        </span>
                      </div>
                      <span style={{ fontSize: '13px', fontWeight: 700, color: '#1E293B' }}>
                        Subtotal: {group.totalWeight.toLocaleString(undefined, { maximumFractionDigits: 1 })} lbs ({(group.totalWeight / 2000).toFixed(2)} tons)
                      </span>
                    </div>
                    <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '12px' }}>
                      <thead>
                        <tr style={{ borderBottom: '1px solid #E2E8F0', color: '#64748B', fontWeight: 600 }}>
                          {activeColumns.map((col) => (
                            <th key={col.id} style={{ padding: '10px 12px', fontSize: '11px', letterSpacing: '0.5px' }}>
                              {col.label}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {group.items.map((item) => (
                          <tr
                            key={item.id}
                            style={{ borderBottom: '1px solid #E2E8F0', color: '#334155' }}
                            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = '#F8FAFC')}
                            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                          >
                            {activeColumns.map((col) => {
                              const cellValue = col.render(item)
                              let cellStyle: React.CSSProperties = { padding: '10px 12px' }
                              if (col.isPiecemark) {
                                cellStyle = { ...cellStyle, fontWeight: 700, color: '#3B82F6' }
                              } else if (col.isSection) {
                                cellStyle = { ...cellStyle, fontWeight: 600, color: '#0F172A' }
                              } else if (col.id === 'status') {
                                cellStyle = { ...cellStyle, color: '#64748B' }
                              }
                              return (
                                <td key={col.id} style={cellStyle}>
                                  {cellValue}
                                </td>
                              )
                            })}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ))}
                
                <div style={{ 
                  marginTop: '16px', 
                  padding: '16px', 
                  backgroundColor: '#0F172A', 
                  borderRadius: '8px', 
                  display: 'flex', 
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)'
                }}>
                  <span style={{ fontSize: '16px', fontWeight: 600, color: '#F8FAFC', textTransform: 'uppercase', letterSpacing: '1px' }}>Grand Total</span>
                  <span style={{ fontSize: '20px', fontWeight: 700, color: '#38BDF8' }}>{(groupedItems.grandTotalWeight / 2000).toFixed(2)} Tons ({(groupedItems.grandTotalWeight).toLocaleString()} lbs)</span>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
