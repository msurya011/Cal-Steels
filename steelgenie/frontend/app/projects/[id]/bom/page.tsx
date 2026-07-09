'use client'

import React, { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { bomApi } from '../../../../lib/api'
import { Spinner } from '../../../../components/ui/Spinner'
import { Download, Play, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'

interface BomItem {
  id: string
  piecemark: string | null
  category: string | null
  qty: number
  section: string | null
  length_in: number | null
  grade: string | null
  weight_lbs: number | null
  is_main: boolean
}

interface BomSummary {
  total_items: number
  total_weight_lbs: number
  total_weight_tons: number
  by_category: Record<string, number>
}

export default function BomPage() {
  const params = useParams()
  const projectId = params?.id as string

  const [items, setItems] = useState<BomItem[]>([])
  const [summary, setSummary] = useState<BomSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [categoryFilter, setCategoryFilter] = useState('')

  const loadBom = async () => {
    setLoading(true)
    try {
      const filters = categoryFilter ? { category: categoryFilter } : {}
      const data = await bomApi.list(projectId, filters)
      const sumData = await bomApi.summary(projectId)
      setItems(data)
      setSummary(sumData)
    } catch {
      toast.error('Failed to load Bill of Materials')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (projectId) {
      loadBom()
    }
  }, [projectId, categoryFilter])

  const handleGenerate = async () => {
    setGenerating(true)
    toast.info('Generating BOM items from plan drawing members...')
    try {
      const res = await bomApi.generate(projectId)
      toast.success(`BOM successfully generated: ${res.generated} items derived`)
      loadBom()
    } catch (err: any) {
      toast.error(err.message || 'BOM generation failed')
    } finally {
      setGenerating(false)
    }
  }

  const handleDownloadCsv = () => {
    const url = bomApi.getExportUrl(projectId)
    window.open(url, '_blank')
  }

  const handleDownloadKiss = () => {
    const url = bomApi.getKissExportUrl(projectId)
    window.open(url, '_blank')
  }

  const handleDownloadEpm = () => {
    const url = bomApi.getEpmExportUrl(projectId)
    window.open(url, '_blank')
  }

  const getFormatLength = (lenIn: number | null) => {
    if (lenIn === null) return '-'
    const ft = Math.floor(lenIn / 12)
    const inch = Math.round(lenIn % 12)
    return `${ft}'-${inch}"`
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box', overflowY: 'auto' }}>
      {/* Top action row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>
            Bill of Materials
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
            AISC main-member takeoff derived from canvas sheet overlays
          </p>
        </div>

        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={handleGenerate}
            disabled={generating}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 16px',
              backgroundColor: generating ? 'rgba(59, 130, 246, 0.15)' : 'rgba(59, 130, 246, 0.1)',
              border: '1px solid rgba(59, 130, 246, 0.25)',
              borderRadius: '6px',
              color: generating ? '#475569' : '#60A5FA',
              fontSize: '13px',
              fontWeight: 600,
              cursor: generating ? 'not-allowed' : 'pointer',
            }}
          >
            <RefreshCw size={14} />
            {generating ? 'Deriving...' : 'Derive from Takeoff'}
          </button>

          <button
            onClick={handleDownloadCsv}
            disabled={items.length === 0}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              backgroundColor: items.length === 0 ? 'rgba(255,255,255,0.02)' : '#1E293B',
              border: '1px solid rgba(59, 130, 246, 0.15)',
              borderRadius: '6px',
              color: items.length === 0 ? '#475569' : '#F1F5F9',
              fontSize: '13px',
              fontWeight: 600,
              cursor: items.length === 0 ? 'not-allowed' : 'pointer',
            }}
          >
            <Download size={14} /> CSV
          </button>

          <button
            onClick={handleDownloadEpm}
            disabled={items.length === 0}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              backgroundColor: items.length === 0 ? 'rgba(255,255,255,0.02)' : '#1E293B',
              border: '1px solid rgba(59, 130, 246, 0.15)',
              borderRadius: '6px',
              color: items.length === 0 ? '#475569' : '#F1F5F9',
              fontSize: '13px',
              fontWeight: 600,
              cursor: items.length === 0 ? 'not-allowed' : 'pointer',
            }}
          >
            <Download size={14} /> Tekla EPM
          </button>

          <button
            onClick={handleDownloadKiss}
            disabled={items.length === 0}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              padding: '8px 14px',
              backgroundColor: items.length === 0 ? 'rgba(255,255,255,0.02)' : '#3B82F6',
              border: 'none',
              borderRadius: '6px',
              color: items.length === 0 ? '#475569' : '#FFFFFF',
              fontSize: '13px',
              fontWeight: 600,
              cursor: items.length === 0 ? 'not-allowed' : 'pointer',
            }}
          >
            <Download size={14} /> KISS (.kss)
          </button>
        </div>
      </div>

      {/* Summary dashboard */}
      {summary && (
        <div style={{ display: 'flex', gap: '16px', marginBottom: '24px', flexWrap: 'wrap' }}>
          {[
            { label: 'Total Weight (tons)', value: summary.total_weight_tons.toFixed(2) },
            { label: 'Derivation items count', value: summary.total_items },
            { label: 'Beams count', value: summary.by_category?.['Beams'] || 0 },
            { label: 'Columns count', value: summary.by_category?.['Columns'] || 0 },
          ].map((stat, i) => (
            <div
              key={i}
              style={{
                flex: '1 1 180px',
                backgroundColor: '#111827',
                border: '1px solid rgba(59, 130, 246, 0.08)',
                borderRadius: '8px',
                padding: '16px',
              }}
            >
              <div style={{ fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>{stat.value}</div>
              <div style={{ fontSize: '11px', color: '#64748B', marginTop: '2px', textTransform: 'uppercase' }}>{stat.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Filter and Grid table view */}
      <div style={{ flex: 1, backgroundColor: '#111827', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '12px 16px', borderBottom: '1px solid rgba(59, 130, 246, 0.08)', display: 'flex', gap: '8px' }}>
          <select
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
            style={{
              padding: '6px 12px',
              backgroundColor: '#1F2937',
              border: '1px solid rgba(59, 130, 246, 0.15)',
              borderRadius: '6px',
              color: '#F1F5F9',
              fontSize: '12px',
              outline: 'none',
            }}
          >
            <option value="">All Categories</option>
            <option value="Beams">Beams</option>
            <option value="Columns">Columns</option>
            <option value="Vertical Braces">Vertical Braces</option>
            <option value="Horizontal Braces">Horizontal Braces</option>
            <option value="Joists">Joists</option>
          </select>
        </div>

        <div style={{ flex: 1, overflow: 'auto' }}>
          {loading ? (
            <div style={{ display: 'flex', height: '200px', alignItems: 'center', justifyContent: 'center' }}>
              <Spinner size="md" />
            </div>
          ) : items.length === 0 ? (
            <div style={{ display: 'flex', height: '200px', alignItems: 'center', justifyContent: 'center', color: '#475569', fontSize: '13px', flexDirection: 'column', gap: '8px' }}>
              <span>No BOM rows derived yet.</span>
              <span style={{ fontSize: '12px' }}>Click "Derive from Takeoff" above to build the AISC shape sheet list.</span>
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left', fontSize: '13px' }}>
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(59, 130, 246, 0.08)', color: '#94A3B8', fontWeight: 600 }}>
                  <th style={{ padding: '12px 16px' }}>Piecemark</th>
                  <th style={{ padding: '12px 16px' }}>Category</th>
                  <th style={{ padding: '12px 16px' }}>Qty</th>
                  <th style={{ padding: '12px 16px' }}>Section</th>
                  <th style={{ padding: '12px 16px' }}>Length</th>
                  <th style={{ padding: '12px 16px' }}>Grade</th>
                  <th style={{ padding: '12px 16px' }}>Weight (lbs)</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr
                    key={item.id}
                    style={{ borderBottom: '1px solid rgba(255, 255, 255, 0.03)', color: '#F1F5F9' }}
                    onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.01)')}
                    onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
                  >
                    <td style={{ padding: '12px 16px', fontWeight: 700, color: '#3B82F6' }}>{item.piecemark || '-'}</td>
                    <td style={{ padding: '12px 16px' }}>{item.category}</td>
                    <td style={{ padding: '12px 16px' }}>{item.qty}</td>
                    <td style={{ padding: '12px 16px', fontWeight: 600 }}>{item.section}</td>
                    <td style={{ padding: '12px 16px' }}>{getFormatLength(item.length_in)}</td>
                    <td style={{ padding: '12px 16px' }}>{item.grade}</td>
                    <td style={{ padding: '12px 16px' }}>{item.weight_lbs !== null ? item.weight_lbs.toLocaleString() : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}
