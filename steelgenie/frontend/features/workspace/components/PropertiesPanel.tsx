import React, { useState, useEffect, useRef } from 'react'
import { Trash2, Check, AlertTriangle, Layers } from 'lucide-react'
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
}

interface PropertiesPanelProps {
  selection: Set<string>
  members: Member[]
  onUpdate: (id: string, data: any) => Promise<void>
  onDelete: (id: string) => Promise<void>
  onBulkUpdate: (ids: string[], data: any) => Promise<void>
  onBulkDelete: (ids: string[]) => Promise<void>
  onClose: () => void
}

export function PropertiesPanel({
  selection,
  members,
  onUpdate,
  onDelete,
  onBulkUpdate,
  onBulkDelete,
  onClose,
}: PropertiesPanelProps) {
  const selectedMembers = members.filter((m) => selection.has(m.id))
  const isMulti = selectedMembers.length > 1
  const member = selectedMembers.length === 1 ? selectedMembers[0] : null

  // Single-select states
  const [kind, setKind] = useState('beam')
  const [section, setSection] = useState('')
  const [length, setLength] = useState('')
  const [grade, setGrade] = useState('A992')
  const [status, setStatus] = useState('active')

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
      setSuggestions([])
      setShowSuggestions(false)
    } else if (isMulti) {
      // Clear bulk states
      setBulkKind('')
      setBulkSection('')
      setBulkLength('')
      setBulkGrade('')
      setBulkStatus('')
      setSuggestions([])
      setShowSuggestions(false)
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

  if (selection.size === 0) {
    return (
      <div
        style={{
          width: '280px',
          backgroundColor: '#111827',
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
      await onUpdate(member.id, {
        kind,
        section: section || null,
        grade: grade || null,
        length_ft: length ? parseFloat(length) : null,
        status,
      })
      onClose()
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

  return (
    <div
      style={{
        width: '280px',
        backgroundColor: '#111827',
        borderLeft: '1px solid rgba(59, 130, 246, 0.1)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        boxSizing: 'border-box',
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '16px',
          borderBottom: '1px solid rgba(59, 130, 246, 0.08)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span style={{ fontSize: '14px', fontWeight: 700, color: '#F1F5F9' }}>
          {isMulti ? `Bulk Edit (${selection.size})` : 'Properties'}
        </span>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: '#64748B', cursor: 'pointer', fontSize: '18px' }}
        >
          &times;
        </button>
      </div>

      {isMulti ? (
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

            {/* Section Autocomplete */}
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

            {/* Grade */}
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
          <div style={{ flex: 1, overflowY: 'auto', padding: '20px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {/* Low AI Confidence warning */}
            {member && member.confidence !== undefined && member.confidence !== null && member.confidence < 0.70 && (
              <div
                style={{
                  padding: '10px 12px',
                  backgroundColor: 'rgba(245, 158, 11, 0.1)',
                  border: '1px solid rgba(245, 158, 11, 0.25)',
                  borderRadius: '6px',
                  color: '#F59E0B',
                  fontSize: '11px',
                  lineHeight: '1.4',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '8px',
                }}
              >
                <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: '1px' }} />
                <span>
                  <strong>Low AI Confidence ({Math.round(member.confidence * 100)}%)</strong> — Please check and confirm the correct section size and length on the sheet drawing.
                </span>
              </div>
            )}

            {/* Type select */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Member Type
              </label>
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value)}
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

            {/* Section Profile input */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', position: 'relative' }} ref={dropdownRef}>
              <label style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Section Size
              </label>
              <input
                value={section}
                onChange={(e) => handleSectionChange(e.target.value, false)}
                onFocus={() => {
                  if (section.trim().length >= 1) {
                    handleSectionChange(section, false)
                  }
                }}
                placeholder="e.g. W12X26"
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
                        setSection(s.designation)
                        setShowSuggestions(false)
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

            {/* Length input */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Length (ft)
              </label>
              <input
                type="number"
                step="0.01"
                value={length}
                onChange={(e) => setLength(e.target.value)}
                placeholder="Not set"
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

            {/* Grade input */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '10px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Steel Grade
              </label>
              <input
                value={grade}
                onChange={(e) => setGrade(e.target.value)}
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
                Verification Status
              </label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
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
                <option value="active">Active (Pending Review)</option>
                <option value="need_review">Need Review</option>
                <option value="verified">Verified</option>
                <option value="rejected">Rejected</option>
                <option value="excluded">Excluded</option>
              </select>
            </div>
          </div>

          {/* Action panel footer */}
          <div style={{ padding: '16px', borderTop: '1px solid rgba(59, 130, 246, 0.08)', display: 'flex', gap: '8px' }}>
            <button
              onClick={handleSingleDelete}
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
            >
              <Trash2 size={16} />
            </button>

            <button
              onClick={handleSingleSave}
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
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}
