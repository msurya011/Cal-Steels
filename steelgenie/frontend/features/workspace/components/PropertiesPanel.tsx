import React, { useState, useEffect, useRef } from 'react'
import { Trash2, Check, AlertTriangle, Layers, Copy, RotateCcw, RotateCw } from 'lucide-react'
import { sectionsApi } from '../../../lib/api'
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
  piecemark?: string | null
}

interface PropertiesPanelProps {
  selection: Set<string>
  members: Member[]
  onUpdate: (id: string, data: any) => Promise<void>
  onDelete: (id: string) => Promise<void>
  onBulkUpdate: (ids: string[], data: any) => Promise<void>
  onBulkDelete: (ids: string[]) => Promise<void>
  onClose: () => void
  pageTos: number
}

// Helper to format decimal feet values into standard Ft'-In Fraction"
function formatFtIn(ftVal: number | null | undefined): string {
  if (ftVal === null || ftVal === undefined) return 'Not set'
  const totalInches = ftVal * 12
  const feet = Math.floor(ftVal)
  const inchesDecimal = totalInches % 12
  const inches = Math.floor(inchesDecimal)
  const fracDecimal = inchesDecimal - inches
  
  // Convert fraction decimal to nearest 1/16, 1/8, 1/4, 1/2
  const sixteenths = Math.round(fracDecimal * 16)
  if (sixteenths === 0) {
    return `${feet}'-${inches}"`
  }
  if (sixteenths === 16) {
    const nextInches = inches + 1
    if (nextInches === 12) {
      return `${feet + 1}'-0"`
    }
    return `${feet}'-${nextInches}"`
  }
  
  // Reduce fraction
  let num = sixteenths
  let den = 16
  while (num % 2 === 0 && den % 2 === 0) {
    num /= 2
    den /= 2
  }
  
  return `${feet}'-${inches} ${num}/${den}"`
}

export function PropertiesPanel({
  selection,
  members,
  onUpdate,
  onDelete,
  onBulkUpdate,
  onBulkDelete,
  onClose,
  pageTos,
}: PropertiesPanelProps) {
  const selectedMembers = members.filter((m) => selection.has(m.id))
  const isMulti = selectedMembers.length > 1
  const member = selectedMembers.length === 1 ? selectedMembers[0] : null

  // Tab state
  const [activeTab, setActiveTab] = useState<'summary' | 'member'>('member')

  // Single-select states
  const [kind, setKind] = useState('beam')
  const [section, setSection] = useState('')
  const [length, setLength] = useState('')
  const [grade, setGrade] = useState('A992')
  const [status, setStatus] = useState('active')
  const [rotation, setRotation] = useState(90)
  const [piecemark, setPiecemark] = useState('')
  
  // Extra geometry states matching the screenshot
  const [copes, setCopes] = useState(0)
  const [camber, setCamber] = useState('')
  const [studs, setStuds] = useState(0)
  const [pourStop, setPourStop] = useState(false)
  const [leftEnd, setLeftEnd] = useState('')
  const [rightEnd, setRightEnd] = useState('')

  // Multi-select bulk states
  const [bulkKind, setBulkKind] = useState('')
  const [bulkSection, setBulkSection] = useState('')
  const [bulkLength, setBulkLength] = useState('')
  const [bulkGrade, setBulkGrade] = useState('')
  const [bulkStatus, setBulkStatus] = useState('')

  const [saving, setSaving] = useState(false)

  // Autocomplete suggestions
  const [suggestions, setSuggestions] = useState<any[]>([])
  const [showSuggestions, setShowSuggestions] = useState(false)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Sync state on member selection change
  useEffect(() => {
    if (member) {
      setKind(member.kind)
      setSection(member.section || '')
      setLength(member.length_ft !== null ? member.length_ft.toString() : '')
      setGrade(member.grade || 'A992')
      setStatus(member.status || 'active')
      setRotation(member.rotation !== undefined ? member.rotation : 90)
      setPiecemark(member.piecemark || '')
      
      const geo = member.geometry || {}
      setCopes(geo.copes || 0)
      setCamber(geo.camber || '')
      setStuds(geo.studs || 0)
      setPourStop(!!geo.pour_stop)
      setLeftEnd(geo.left_end || '')
      setRightEnd(geo.right_end || '')
      
      setSuggestions([])
      setShowSuggestions(false)
      setActiveTab('member') // Auto switch to member tab on select
    } else if (isMulti) {
      // Clear bulk states
      setBulkKind('')
      setBulkSection('')
      setBulkLength('')
      setBulkGrade('')
      setBulkStatus('')
      setSuggestions([])
      setShowSuggestions(false)
      setActiveTab('member')
    }
  }, [member, isMulti])

  // Click outside to close suggest dropdown
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setShowSuggestions(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const handleSectionChange = async (val: string, isBulk = false) => {
    if (isBulk) {
      setBulkSection(val)
    } else {
      setSection(val)
    }

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

  // Auto-save logic triggers update to parent / database instantly
  const autoSave = async (updatedFields: any) => {
    if (!member) return
    try {
      const updatedGeo = updatedFields.geometry || {}
      
      const geoUpdate = {
        ...(member.geometry || {}),
        copes: updatedGeo.hasOwnProperty('copes') ? updatedGeo.copes : copes,
        camber: updatedGeo.hasOwnProperty('camber') ? updatedGeo.camber : camber,
        studs: updatedGeo.hasOwnProperty('studs') ? updatedGeo.studs : studs,
        pour_stop: updatedGeo.hasOwnProperty('pour_stop') ? updatedGeo.pour_stop : pourStop,
        left_end: updatedGeo.hasOwnProperty('left_end') ? updatedGeo.left_end : (leftEnd || formatFtIn(pageTos)),
        right_end: updatedGeo.hasOwnProperty('right_end') ? updatedGeo.right_end : (rightEnd || formatFtIn(pageTos)),
      }
      
      await onUpdate(member.id, {
        kind: updatedFields.hasOwnProperty('kind') ? updatedFields.kind : kind,
        section: updatedFields.hasOwnProperty('section') ? updatedFields.section : (section || null),
        grade: updatedFields.hasOwnProperty('grade') ? updatedFields.grade : grade,
        length_ft: updatedFields.hasOwnProperty('length') 
          ? (updatedFields.length ? parseFloat(updatedFields.length) : null) 
          : (length ? parseFloat(length) : null),
        status: updatedFields.hasOwnProperty('status') ? updatedFields.status : status,
        rotation: updatedFields.hasOwnProperty('rotation') ? updatedFields.rotation : rotation,
        piecemark: updatedFields.hasOwnProperty('piecemark') ? updatedFields.piecemark : (piecemark || null),
        geometry: geoUpdate,
      })
    } catch {
      // ignore
    }
  }

  if (selection.size === 0) {
    return (
      <div
        style={{
          width: '320px',
          backgroundColor: '#0F172A',
          borderLeft: '1px solid rgba(59, 130, 246, 0.1)',
          padding: '24px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          textAlign: 'center',
          color: '#475569',
          fontSize: '13px',
          height: '100%',
          boxSizing: 'border-box',
          flexShrink: 0,
        }}
      >
        <Layers size={28} style={{ marginBottom: '12px', color: '#1E293B' }} />
        <span>Select member(s) on the drawing overlay or tree to edit properties</span>
      </div>
    )
  }

  const handleSingleSave = async () => {
    if (!member) return
    setSaving(true)
    try {
      await autoSave({})
      toast.success('Member properties saved')
    } catch {
      // error toast handled in parent
    } finally {
      setSaving(false)
    }
  }

  const handleSingleDelete = async () => {
    if (!member) return
    if (confirm('Delete this member overlay?')) {
      await onDelete(member.id)
      onClose()
    }
  }

  const handleBulkSave = async () => {
    const ids = Array.from(selection)
    const updateData: any = {}
    if (bulkKind) updateData.kind = bulkKind
    if (bulkSection) updateData.section = bulkSection
    if (bulkGrade) updateData.grade = bulkGrade
    if (bulkLength) updateData.length_ft = parseFloat(bulkLength)
    if (bulkStatus) updateData.status = bulkStatus

    if (Object.keys(updateData).length === 0) {
      toast.error('No changes selected to apply')
      return
    }

    setSaving(true)
    try {
      await onBulkUpdate(ids, updateData)
      onClose()
    } catch {
      // error toast handled in parent
    } finally {
      setSaving(false)
    }
  }

  const handleBulkDeleteSubmit = async () => {
    const ids = Array.from(selection)
    if (confirm(`Delete all ${ids.length} selected members?`)) {
      setSaving(true)
      try {
        await onBulkDelete(ids)
        onClose()
      } catch {
        // error toast handled in parent
      } finally {
        setSaving(false)
      }
    }
  }

  // Summary logic for selected members count
  const beamCount = members.filter(m => m.kind === 'beam').length
  const columnCount = members.filter(m => m.kind === 'column').length
  const braceCount = members.filter(m => m.kind === 'vbrace' || m.kind === 'hbrace' || m.kind === 'brace').length

  return (
    <div
      style={{
        width: '320px',
        backgroundColor: '#0F172A',
        borderLeft: '1px solid rgba(59, 130, 246, 0.1)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        boxSizing: 'border-box',
        flexShrink: 0,
      }}
    >
      {/* Header with Title and close button */}
      <div
        style={{
          padding: '16px',
          borderBottom: '1px solid rgba(59, 130, 246, 0.08)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ fontSize: '15px', fontWeight: 700, color: '#F1F5F9' }}>
            {isMulti ? `Bulk Edit (${selection.size})` : 'Properties'}
          </span>
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: '#64748B', cursor: 'pointer', fontSize: '20px' }}
        >
          &times;
        </button>
      </div>

      {/* Tabs bar: Summary vs Member */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid rgba(59, 130, 246, 0.05)' }}>
        <div style={{ display: 'flex', backgroundColor: '#1E293B', borderRadius: '8px', padding: '3px' }}>
          <button
            onClick={() => setActiveTab('summary')}
            style={{
              flex: 1,
              padding: '6px',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: activeTab === 'summary' ? '#2563EB' : 'transparent',
              color: activeTab === 'summary' ? '#FFFFFF' : '#94A3B8',
              fontWeight: 600,
              fontSize: '12px',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            Summary
          </button>
          <button
            onClick={() => setActiveTab('member')}
            style={{
              flex: 1,
              padding: '6px',
              borderRadius: '6px',
              border: 'none',
              backgroundColor: activeTab === 'member' ? '#2563EB' : 'transparent',
              color: activeTab === 'member' ? '#FFFFFF' : '#94A3B8',
              fontWeight: 600,
              fontSize: '12px',
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            Member
          </button>
        </div>
      </div>

      {activeTab === 'summary' ? (
        // ── SUMMARY TAB ──────────────────────────────────────────────────────
        <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px', color: '#F1F5F9' }}>
          <span style={{ fontSize: '13px', fontWeight: 600, color: '#94A3B8', borderBottom: '1px solid rgba(255, 255, 255, 0.05)', paddingBottom: '6px' }}>
            Page Statistics
          </span>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
              <span>Total Beams:</span>
              <span style={{ fontWeight: 700, color: '#3B82F6' }}>{beamCount}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
              <span>Total Columns:</span>
              <span style={{ fontWeight: 700, color: '#10B981' }}>{columnCount}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
              <span>Total Braces:</span>
              <span style={{ fontWeight: 700, color: '#F59E0B' }}>{braceCount}</span>
            </div>
          </div>
        </div>
      ) : isMulti ? (
        // ── MULTI SELECTION BULK EDIT FORM ───────────────────────────────────
        <>
          <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <span style={{ fontSize: '11px', color: '#64748B' }}>
              Fields left blank or unchanged will not be modified on selected members.
            </span>

            {/* Kind Select */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Member Type
              </label>
              <select
                value={bulkKind}
                onChange={(e) => setBulkKind(e.target.value)}
                style={{
                  padding: '8px 10px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '6px',
                  color: '#F1F5F9',
                  fontSize: '13px',
                  outline: 'none',
                }}
              >
                <option value="">No change</option>
                <option value="beam">Beam</option>
                <option value="column">Column</option>
                <option value="vbrace">Vertical Brace</option>
                <option value="hbrace">Horizontal Brace</option>
                <option value="joist">Joist</option>
              </select>
            </div>

            {/* Section Size */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', position: 'relative' }} ref={dropdownRef}>
              <label style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Section Size
              </label>
              <input
                value={bulkSection}
                onChange={(e) => handleSectionChange(e.target.value, true)}
                placeholder="No change"
                style={{
                  padding: '8px 10px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '6px',
                  color: '#F1F5F9',
                  fontSize: '13px',
                  outline: 'none',
                }}
              />
              {showSuggestions && suggestions.length > 0 && (
                <div
                  style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    right: 0,
                    zIndex: 50,
                    backgroundColor: '#1E293B',
                    border: '1px solid rgba(59, 130, 246, 0.2)',
                    borderRadius: '6px',
                    maxHeight: '180px',
                    overflowY: 'auto',
                    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.5)',
                    marginTop: '4px',
                  }}
                >
                  {suggestions.map((s) => (
                    <div
                      key={s.designation}
                      onClick={() => {
                        setBulkSection(s.designation)
                        setShowSuggestions(false)
                      }}
                      style={{
                        padding: '8px 12px',
                        cursor: 'pointer',
                        fontSize: '12px',
                        color: '#F1F5F9',
                        borderBottom: '1px solid rgba(59, 130, 246, 0.05)',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(59, 130, 246, 0.15)')}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                    >
                      <div style={{ fontWeight: 600 }}>{s.designation}</div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Length */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Length (ft)
              </label>
              <input
                type="number"
                step="0.01"
                value={bulkLength}
                onChange={(e) => setBulkLength(e.target.value)}
                placeholder="No change"
                style={{
                  padding: '8px 10px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '6px',
                  color: '#F1F5F9',
                  fontSize: '13px',
                  outline: 'none',
                }}
              />
            </div>

            {/* Steel Grade */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Steel Grade
              </label>
              <input
                value={bulkGrade}
                onChange={(e) => setBulkGrade(e.target.value)}
                placeholder="No change"
                style={{
                  padding: '8px 10px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '6px',
                  color: '#F1F5F9',
                  fontSize: '13px',
                  outline: 'none',
                }}
              />
            </div>

            {/* Status Select */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Review Status
              </label>
              <select
                value={bulkStatus}
                onChange={(e) => setBulkStatus(e.target.value)}
                style={{
                  padding: '8px 10px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '6px',
                  color: '#F1F5F9',
                  fontSize: '13px',
                  outline: 'none',
                }}
              >
                <option value="">No change</option>
                <option value="active">Active (Pending Review)</option>
                <option value="need_review">Needs Manual Review</option>
                <option value="verified">Verified (Approved)</option>
                <option value="rejected">Rejected</option>
                <option value="excluded">Excluded</option>
              </select>
            </div>
          </div>

          {/* Footer Action buttons */}
          <div style={{ padding: '16px', borderTop: '1px solid rgba(59, 130, 246, 0.08)', display: 'flex', gap: '8px' }}>
            <button
              onClick={handleBulkDeleteSubmit}
              style={{
                padding: '10px',
                backgroundColor: 'transparent',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                borderRadius: '6px',
                color: '#EF4444',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
              title="Delete all selected"
            >
              <Trash2 size={16} />
            </button>
            <button
              onClick={handleBulkSave}
              disabled={saving}
              style={{
                flex: 1,
                padding: '10px',
                backgroundColor: '#3B82F6',
                border: 'none',
                borderRadius: '6px',
                color: '#FFFFFF',
                fontWeight: 600,
                fontSize: '13px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '6px',
              }}
            >
              <Check size={14} />
              {saving ? 'Applying...' : 'Apply Changes'}
            </button>
          </div>
        </>
      ) : (
        // ── SINGLE SELECTION PROPERTIES FORM ──────────────────────────────────
        <>
          <div style={{ flex: 1, overflowY: 'auto', padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
            
            {/* Accordion header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#94A3B8', fontSize: '11px', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.5px', borderBottom: '1px solid rgba(255, 255, 255, 0.05)', paddingBottom: '6px' }}>
              <span>Member Properties</span>
              <span style={{ fontSize: '10px' }}>▼</span>
            </div>

            {/* Properties subheader */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: '13px', fontWeight: 600, color: '#F1F5F9' }}>Properties</span>
              <a href="#" style={{ fontSize: '11px', color: '#F59E0B', textDecoration: 'none' }}>More...</a>
            </div>

            {/* Linear Copy Button */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: 'rgba(30, 41, 59, 0.4)', padding: '8px 12px', borderRadius: '6px', border: '1px solid rgba(59, 130, 246, 0.05)' }}>
              <span style={{ fontSize: '13px', color: '#94A3B8' }}>Linear Copy</span>
              <Copy size={15} style={{ cursor: 'pointer', color: '#3B82F6' }} onClick={() => toast.info("Linear copy action triggered")} />
            </div>

            {/* Rotation toggle and input */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Rotation</label>
              <div style={{ display: 'flex', gap: '6px' }}>
                <input
                  type="number"
                  value={rotation}
                  onChange={(e) => {
                    const rotVal = parseInt(e.target.value) || 0
                    setRotation(rotVal)
                  }}
                  onBlur={() => autoSave({ rotation })}
                  style={{
                    flex: 1,
                    padding: '8px 10px',
                    backgroundColor: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid rgba(59, 130, 246, 0.15)',
                    borderRadius: '6px',
                    color: '#F1F5F9',
                    fontSize: '13px',
                    outline: 'none',
                  }}
                />
                <button
                  onClick={() => {
                    const next = (rotation - 90 + 360) % 360
                    setRotation(next)
                    autoSave({ rotation: next })
                  }}
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid rgba(59, 130, 246, 0.15)',
                    borderRadius: '6px',
                    color: '#F1F5F9',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  <RotateCcw size={14} />
                </button>
                <button
                  onClick={() => {
                    const next = (rotation + 90) % 360
                    setRotation(next)
                    autoSave({ rotation: next })
                  }}
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid rgba(59, 130, 246, 0.15)',
                    borderRadius: '6px',
                    color: '#F1F5F9',
                    cursor: 'pointer',
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  <RotateCw size={14} />
                </button>
              </div>
            </div>

            {/* Piecemark & Copes Row */}
            <div style={{ display: 'flex', gap: '10px' }}>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Piecemark</label>
                <input
                  value={piecemark}
                  onChange={(e) => setPiecemark(e.target.value)}
                  onBlur={() => autoSave({ piecemark })}
                  placeholder="B_76"
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid rgba(59, 130, 246, 0.15)',
                    borderRadius: '6px',
                    color: '#F1F5F9',
                    fontSize: '13px',
                    outline: 'none',
                    width: '100%',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Copes</label>
                <input
                  type="number"
                  value={copes}
                  onChange={(e) => setCopes(parseInt(e.target.value) || 0)}
                  onBlur={() => autoSave({ geometry: { copes } })}
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid rgba(59, 130, 246, 0.15)',
                    borderRadius: '6px',
                    color: '#F1F5F9',
                    fontSize: '13px',
                    outline: 'none',
                    width: '100%',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>

            {/* Length p-p & Length f-f Row */}
            <div style={{ display: 'flex', gap: '10px' }}>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Length <sub>p-p</sub></label>
                <input
                  readOnly
                  value={formatFtIn(length ? parseFloat(length) : null)}
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    borderRadius: '6px',
                    color: '#94A3B8',
                    fontSize: '13px',
                    outline: 'none',
                    width: '100%',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Length <sub>f-f</sub></label>
                <input
                  readOnly
                  value={formatFtIn(length ? parseFloat(length) - 0.75 : null)} // default face-to-face offset is 3/4" (9 in)
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    borderRadius: '6px',
                    color: '#94A3B8',
                    fontSize: '13px',
                    outline: 'none',
                    width: '100%',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>

            {/* Member Type select */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Member Type</label>
              <select
                value={kind}
                onChange={(e) => {
                  const val = e.target.value
                  setKind(val)
                  autoSave({ kind: val })
                }}
                style={{
                  padding: '8px 10px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '6px',
                  color: '#F1F5F9',
                  fontSize: '13px',
                  outline: 'none',
                }}
              >
                <option value="beam">Beam</option>
                <option value="column">Column</option>
                <option value="vbrace">Vertical Brace</option>
                <option value="hbrace">Horizontal Brace</option>
                <option value="joist">Joist</option>
              </select>
            </div>

            {/* Section Size Autocomplete */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', position: 'relative' }} ref={dropdownRef}>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>
                Section Size {!section && <AlertTriangle size={12} style={{ display: 'inline', color: '#EF4444', marginLeft: '4px' }} />}
              </label>
              <input
                value={section}
                onChange={(e) => handleSectionChange(e.target.value, false)}
                onBlur={() => autoSave({ section })}
                onFocus={() => {
                  if (section.trim().length >= 1) {
                    handleSectionChange(section, false)
                  }
                }}
                placeholder="Select section size"
                style={{
                  padding: '8px 10px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: section ? '1px solid rgba(59, 130, 246, 0.15)' : '1px solid #EF4444',
                  borderRadius: '6px',
                  color: '#F1F5F9',
                  fontSize: '13px',
                  outline: 'none',
                }}
              />
              {!section && (
                <span style={{ fontSize: '11px', color: '#F59E0B', marginTop: '2px', fontWeight: 600 }}>
                  {kind[0].toUpperCase() + kind.slice(1)} section size is empty
                </span>
              )}
              {showSuggestions && suggestions.length > 0 && (
                <div
                  style={{
                    position: 'absolute',
                    top: '100%',
                    left: 0,
                    right: 0,
                    zIndex: 50,
                    backgroundColor: '#1E293B',
                    border: '1px solid rgba(59, 130, 246, 0.2)',
                    borderRadius: '6px',
                    maxHeight: '180px',
                    overflowY: 'auto',
                    boxShadow: '0 4px 12px rgba(0, 0, 0, 0.5)',
                    marginTop: '4px',
                  }}
                >
                  {suggestions.map((s) => (
                    <div
                      key={s.designation}
                      onClick={() => {
                        setSection(s.designation)
                        setShowSuggestions(false)
                        autoSave({ section: s.designation })
                      }}
                      style={{
                        padding: '8px 12px',
                        cursor: 'pointer',
                        fontSize: '12px',
                        color: '#F1F5F9',
                        borderBottom: '1px solid rgba(59, 130, 246, 0.05)',
                        transition: 'background-color 0.2s',
                      }}
                      onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(59, 130, 246, 0.15)')}
                      onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                    >
                      <div style={{ fontWeight: 600 }}>{s.designation}</div>
                      <div style={{ fontSize: '10px', color: '#64748B' }}>
                        {s.weight_per_ft} lbs/ft • d={s.depth_in}" • bf={s.flange_width_in}"
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Verification Status */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Status</label>
              <select
                value={status}
                onChange={(e) => {
                  const val = e.target.value
                  setStatus(val)
                  autoSave({ status: val })
                }}
                style={{
                  padding: '8px 10px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '6px',
                  color: '#F1F5F9',
                  fontSize: '13px',
                  outline: 'none',
                }}
              >
                <option value="active">Not Started</option>
                <option value="need_review">Need Review</option>
                <option value="verified">Verified</option>
                <option value="rejected">Rejected</option>
              </select>
            </div>

            {/* Camber & Studs Row */}
            <div style={{ display: 'flex', gap: '10px' }}>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Camber</label>
                <input
                  value={camber}
                  onChange={(e) => setCamber(e.target.value)}
                  onBlur={() => autoSave({ geometry: { camber } })}
                  placeholder="Enter camber"
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid rgba(59, 130, 246, 0.15)',
                    borderRadius: '6px',
                    color: '#F1F5F9',
                    fontSize: '13px',
                    outline: 'none',
                    width: '100%',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Studs</label>
                <input
                  type="number"
                  value={studs}
                  onChange={(e) => setStuds(parseInt(e.target.value) || 0)}
                  onBlur={() => autoSave({ geometry: { studs } })}
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(30, 41, 59, 0.8)',
                    border: '1px solid rgba(59, 130, 246, 0.15)',
                    borderRadius: '6px',
                    color: '#F1F5F9',
                    fontSize: '13px',
                    outline: 'none',
                    width: '100%',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>

            {/* Left End & Right End Elevations Row */}
            <div style={{ display: 'flex', gap: '10px' }}>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Left End</label>
                  <span style={{ fontSize: '11px', cursor: 'pointer' }}>🔒</span>
                </div>
                <input
                  readOnly
                  value={leftEnd || formatFtIn(pageTos)}
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    borderRadius: '6px',
                    color: '#94A3B8',
                    fontSize: '13px',
                    outline: 'none',
                    width: '100%',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8' }}>Right End</label>
                  <span style={{ fontSize: '11px', cursor: 'pointer' }}>🔒</span>
                </div>
                <input
                  readOnly
                  value={rightEnd || formatFtIn(pageTos)}
                  style={{
                    padding: '8px 10px',
                    backgroundColor: 'rgba(15, 23, 42, 0.6)',
                    border: '1px solid rgba(255, 255, 255, 0.05)',
                    borderRadius: '6px',
                    color: '#94A3B8',
                    fontSize: '13px',
                    outline: 'none',
                    width: '100%',
                    boxSizing: 'border-box',
                  }}
                />
              </div>
            </div>

            {/* Pour Stop checkbox */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '4px' }}>
              <input
                type="checkbox"
                id="pourStop"
                checked={pourStop}
                onChange={(e) => {
                  const val = e.target.checked
                  setPourStop(val)
                  autoSave({ geometry: { pour_stop: val } })
                }}
                style={{ cursor: 'pointer', width: '15px', height: '15px' }}
              />
              <label htmlFor="pourStop" style={{ fontSize: '12px', color: '#F1F5F9', cursor: 'pointer', fontWeight: 600 }}>
                Pour Stop
              </label>
            </div>

            {/* Connections sub-accordion */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 12px', backgroundColor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '6px', cursor: 'pointer', marginTop: '4px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#F1F5F9' }}>Connections</span>
              <span style={{ color: '#94A3B8', fontSize: '10px' }}>&gt;</span>
            </div>

          </div>

          {/* Action panel footer */}
          <div style={{ padding: '16px', borderTop: '1px solid rgba(59, 130, 246, 0.08)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <button
              onClick={handleSingleSave}
              disabled={saving}
              style={{
                width: '100%',
                padding: '10px',
                backgroundColor: '#3B82F6',
                border: 'none',
                borderRadius: '6px',
                color: '#FFFFFF',
                fontWeight: 600,
                fontSize: '13px',
                cursor: 'pointer',
              }}
            >
              {saving ? 'Saving...' : 'Save properties'}
            </button>
            <button
              onClick={handleSingleDelete}
              style={{
                width: '100%',
                padding: '10px',
                backgroundColor: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.25)',
                borderRadius: '6px',
                color: '#EF4444',
                fontWeight: 600,
                fontSize: '13px',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
              }}
            >
              <Trash2 size={15} />
              Delete
            </button>
          </div>
        </>
      )}
    </div>
  )
}
