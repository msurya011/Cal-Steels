import React, { useState } from 'react'

interface CreateProjectModalProps {
  onClose: () => void
  onCreate: (data: {
    name: string
    number: string
    design_standard: string
    unit_system: string
    location: string
    description: string
  }) => Promise<void>
}

const STANDARDS = ['AISC', 'IS 800', 'Eurocode 3', 'BS 5950', 'AS 4100']
const UNITS = ['imperial', 'metric']

export function CreateProjectModal({ onClose, onCreate }: CreateProjectModalProps) {
  const [name, setName] = useState('')
  const [number, setNumber] = useState('')
  const [standard, setStandard] = useState('AISC')
  const [units, setUnits] = useState('imperial')
  const [location, setLocation] = useState('')
  const [description, setDescription] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return

    setLoading(true)
    setError(null)
    try {
      await onCreate({
        name,
        number: number || '',
        design_standard: standard,
        unit_system: units,
        location: location || '',
        description: description || '',
      })
      onClose()
    } catch (err: any) {
      setError(err.message || 'Failed to create project')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'rgba(0, 0, 0, 0.65)',
        backdropFilter: 'blur(4px)',
        padding: '20px',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '480px',
          backgroundColor: '#111827',
          border: '1px solid rgba(59, 130, 246, 0.2)',
          borderRadius: '16px',
          padding: '32px',
          boxShadow: '0 25px 60px rgba(0, 0, 0, 0.65)',
        }}
      >
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '24px',
          }}
        >
          <h2 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>
            New Project
          </h2>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: '#64748B',
              cursor: 'pointer',
              fontSize: '24px',
              lineHeight: 1,
            }}
          >
            &times;
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Project Name *
            </label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. West Tower Framing"
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(30, 41, 59, 0.8)',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                borderRadius: '8px',
                color: '#F1F5F9',
                fontSize: '14px',
                outline: 'none',
              }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Project Number
            </label>
            <input
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              placeholder="e.g. SG-2024-001"
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(30, 41, 59, 0.8)',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                borderRadius: '8px',
                color: '#F1F5F9',
                fontSize: '14px',
                outline: 'none',
              }}
            />
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Standard
              </label>
              <select
                value={standard}
                onChange={(e) => setStandard(e.target.value)}
                style={{
                  padding: '10px 14px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '8px',
                  color: '#F1F5F9',
                  fontSize: '14px',
                  outline: 'none',
                }}
              >
                {STANDARDS.map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
                Units
              </label>
              <select
                value={units}
                onChange={(e) => setUnits(e.target.value)}
                style={{
                  padding: '10px 14px',
                  backgroundColor: 'rgba(30, 41, 59, 0.8)',
                  border: '1px solid rgba(59, 130, 246, 0.15)',
                  borderRadius: '8px',
                  color: '#F1F5F9',
                  fontSize: '14px',
                  outline: 'none',
                }}
              >
                {UNITS.map((u) => (
                  <option key={u} value={u}>{u}</option>
                ))}
              </select>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Location
            </label>
            <input
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="e.g. Chicago, IL"
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(30, 41, 59, 0.8)',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                borderRadius: '8px',
                color: '#F1F5F9',
                fontSize: '14px',
                outline: 'none',
              }}
            />
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            <label style={{ fontSize: '11px', fontWeight: 600, color: '#94A3B8', textTransform: 'uppercase', letterSpacing: '0.6px' }}>
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Project description or notes..."
              rows={3}
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(30, 41, 59, 0.8)',
                border: '1px solid rgba(59, 130, 246, 0.15)',
                borderRadius: '8px',
                color: '#F1F5F9',
                fontSize: '14px',
                outline: 'none',
                resize: 'none',
              }}
            />
          </div>

          {error && (
            <div
              style={{
                padding: '10px 14px',
                backgroundColor: 'rgba(239, 68, 68, 0.08)',
                border: '1px solid rgba(239, 68, 68, 0.2)',
                borderRadius: '8px',
                color: '#F87171',
                fontSize: '13px',
              }}
            >
              &#9888; {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
            <button
              type="button"
              onClick={onClose}
              style={{
                flex: 1,
                padding: '12px',
                backgroundColor: 'transparent',
                border: '1px solid rgba(100, 116, 139, 0.25)',
                borderRadius: '8px',
                color: '#94A3B8',
                fontSize: '14px',
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={loading}
              style={{
                flex: 2,
                padding: '12px',
                backgroundColor: loading ? '#1D4ED8' : '#3B82F6',
                border: 'none',
                borderRadius: '8px',
                color: '#FFFFFF',
                fontSize: '14px',
                fontWeight: 600,
                cursor: loading ? 'not-allowed' : 'pointer',
                boxShadow: '0 4px 14px rgba(59, 130, 246, 0.35)',
              }}
            >
              {loading ? 'Creating...' : 'Create Project'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
