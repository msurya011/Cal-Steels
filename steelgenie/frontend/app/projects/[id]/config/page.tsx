'use client'

import React, { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { configApi } from '../../../../lib/api'
import { Spinner } from '../../../../components/ui/Spinner'
import { Settings, Save, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'

export default function ConfigPage() {
  const params = useParams()
  const projectId = params?.id as string

  const [config, setConfig] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  // Form states
  const [designMethod, setDesignMethod] = useState('ASD')
  const [udlPercent, setUdlPercent] = useState('50')
  const [maxSpliceHeight, setMaxSpliceHeight] = useState('35.0')
  const [steelGradeW, setSteelGradeW] = useState('A992')

  useEffect(() => {
    if (!projectId) return
    configApi
      .get(projectId)
      .then((data) => {
        const payload = data.payload || {}
        setConfig(payload)
        setDesignMethod(payload.design_method || 'ASD')
        setUdlPercent(payload.beam_end_reaction?.udl_percent?.toString() || '50')
        setMaxSpliceHeight(payload.connection_types?.max_splice_height_ft?.toString() || '35.0')
        setSteelGradeW(payload.materials?.W || 'A992')
        setLoading(false)
      })
      .catch(() => {
        toast.error('Failed to load project configuration')
        setLoading(false)
      })
  }, [projectId])

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setSaving(true)
    try {
      const payload = {
        ...config,
        design_method: designMethod,
        beam_end_reaction: {
          ...config?.beam_end_reaction,
          udl_percent: parseInt(udlPercent) || 50,
        },
        connection_types: {
          ...config?.connection_types,
          max_splice_height_ft: parseFloat(maxSpliceHeight) || 35.0,
        },
        materials: {
          ...config?.materials,
          W: steelGradeW,
        },
      }
      await configApi.update(projectId, payload)
      toast.success('Engineering configuration updated successfully')
    } catch {
      toast.error('Failed to save configuration settings')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center' }}>
        <Spinner size="md" />
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box', overflowY: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>
            Engineering Configuration
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
            Configure design methods, materials specification, and connection standards for estimates
          </p>
        </div>
      </div>

      <form onSubmit={handleSave} style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '600px' }}>
        {/* Method configuration */}
        <div style={{ backgroundColor: '#111827', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', padding: '20px' }}>
          <h3 style={{ margin: '0 0 16px', fontSize: '14px', fontWeight: 700, color: '#F1F5F9' }}>Design Settings</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '11px', color: '#94A3B8', fontWeight: 600 }}>Design Method</label>
              <select
                value={designMethod}
                onChange={(e) => setDesignMethod(e.target.value)}
                style={{ padding: '8px 12px', backgroundColor: '#1F2937', border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '6px', color: '#F1F5F9', fontSize: '13px' }}
              >
                <option value="ASD">ASD (Allowable Strength Design)</option>
                <option value="LRFD">LRFD (Load and Resistance Factor Design)</option>
              </select>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '11px', color: '#94A3B8', fontWeight: 600 }}>Beam End Reaction (% UDL)</label>
              <input
                type="number"
                value={udlPercent}
                onChange={(e) => setUdlPercent(e.target.value)}
                style={{ padding: '8px 12px', backgroundColor: '#1F2937', border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '6px', color: '#F1F5F9', fontSize: '13px' }}
              />
            </div>
          </div>
        </div>

        {/* Splice and Connection defaults */}
        <div style={{ backgroundColor: '#111827', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', padding: '20px' }}>
          <h3 style={{ margin: '0 0 16px', fontSize: '14px', fontWeight: 700, color: '#F1F5F9' }}>Connections & Splices</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '11px', color: '#94A3B8', fontWeight: 600 }}>Max Splice Height (ft)</label>
              <input
                type="number"
                step="0.1"
                value={maxSpliceHeight}
                onChange={(e) => setMaxSpliceHeight(e.target.value)}
                style={{ padding: '8px 12px', backgroundColor: '#1F2937', border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '6px', color: '#F1F5F9', fontSize: '13px' }}
              />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <label style={{ fontSize: '11px', color: '#94A3B8', fontWeight: 600 }}>W-Shapes Primary Grade</label>
              <input
                value={steelGradeW}
                onChange={(e) => setSteelGradeW(e.target.value)}
                style={{ padding: '8px 12px', backgroundColor: '#1F2937', border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '6px', color: '#F1F5F9', fontSize: '13px' }}
              />
            </div>
          </div>
        </div>

        <button
          type="submit"
          disabled={saving}
          style={{
            alignSelf: 'flex-start',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '10px 20px',
            backgroundColor: '#3B82F6',
            border: 'none',
            borderRadius: '6px',
            color: '#FFFFFF',
            fontSize: '13px',
            fontWeight: 600,
            cursor: saving ? 'not-allowed' : 'pointer',
            boxShadow: '0 4px 14px rgba(59, 130, 246, 0.35)',
          }}
        >
          <Save size={16} />
          {saving ? 'Saving Settings...' : 'Save Configuration'}
        </button>
      </form>
    </div>
  )
}
