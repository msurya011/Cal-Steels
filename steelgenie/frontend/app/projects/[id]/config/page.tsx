'use client'

import React, { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { configApi } from '../../../../lib/api'
import { Spinner } from '../../../../components/ui/Spinner'
import { Save, RotateCcw, Info } from 'lucide-react'
import { toast } from 'sonner'

// ── Shared field chrome ────────────────────────────────────────────────────
function Badge({ text, color }: { text: string; color: string }) {
  return (
    <span style={{
      fontSize: '9px', fontWeight: 700, padding: '2px 6px', borderRadius: '4px',
      backgroundColor: `${color}22`, color, textTransform: 'uppercase', letterSpacing: '0.4px',
    }}>
      {text}
    </span>
  )
}

function Field({ label, badge, help, children }: { label: string; badge?: { text: string; color: string }; help?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
        <label style={{ fontSize: '11px', color: '#94A3B8', fontWeight: 600 }}>{label}</label>
        {badge && <Badge text={badge.text} color={badge.color} />}
        {help && (
          <span title={help} style={{ cursor: 'help', display: 'inline-flex', alignItems: 'center' }}>
            <Info size={11} color="#475569" />
          </span>
        )}
      </div>
      {children}
    </div>
  )
}

const selectStyle: React.CSSProperties = {
  padding: '8px 12px', backgroundColor: '#1F2937', border: '1px solid rgba(59, 130, 246, 0.15)',
  borderRadius: '6px', color: '#F1F5F9', fontSize: '13px', width: '100%', boxSizing: 'border-box',
}
const inputStyle: React.CSSProperties = { ...selectStyle }
const sectionStyle: React.CSSProperties = { backgroundColor: '#111827', border: '1px solid rgba(59, 130, 246, 0.08)', borderRadius: '8px', padding: '20px' }
const sectionTitleStyle: React.CSSProperties = { margin: '0 0 16px', fontSize: '14px', fontWeight: 700, color: '#F1F5F9' }
const gridStyle: React.CSSProperties = { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }

const MATERIAL_ROWS: Array<[string, string]> = [
  ['W', 'W-Shapes'], ['WT', 'WT-Shapes'], ['S', 'S-Shapes'], ['ST', 'ST-Shapes'],
  ['C', 'Channels (C)'], ['L', 'Angles (L)'], ['M', 'M-Shapes'], ['MT', 'MT-Shapes'],
  ['MC', 'MC-Channels'], ['HP', 'HP-Piles'], ['HSS_rect', 'HSS Rectangular'],
  ['HSS_round', 'HSS Round'], ['PIPE', 'Pipe'], ['ANCHOR', 'Anchor Rods'],
  ['WELD_STUD', 'Weld Studs'], ['PLATE', 'Plate'], ['BOLT', 'Bolts'], ['ELECTRODE', 'Welding Electrode'],
]

export default function ConfigPage() {
  const params = useParams()
  const projectId = params?.id as string

  const [config, setConfig] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [resetting, setResetting] = useState(false)

  const load = () => {
    setLoading(true)
    configApi
      .get(projectId)
      .then((data) => setConfig(data.payload || {}))
      .catch(() => toast.error('Failed to load project configuration'))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (projectId) load()
  }, [projectId])

  const set = (path: string[], value: any) => {
    setConfig((prev: any) => {
      const next = { ...prev }
      let node = next
      for (let i = 0; i < path.length - 1; i++) {
        node[path[i]] = { ...(node[path[i]] || {}) }
        node = node[path[i]]
      }
      node[path[path.length - 1]] = value
      return next
    })
  }
  const get = (path: string[], fallback: any = '') =>
    path.reduce((n, k) => (n && n[k] !== undefined ? n[k] : undefined), config) ?? fallback

  const handleSave = async () => {
    setSaving(true)
    try {
      await configApi.update(projectId, config)
      toast.success('Engineering configuration updated successfully')
    } catch {
      toast.error('Failed to save configuration settings')
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    if (!confirm('Reset all engineering configuration to defaults? Unsaved changes will be lost.')) return
    setResetting(true)
    try {
      const resp = await configApi.reset(projectId)
      setConfig(resp.payload || {})
      toast.success('Configuration reset to defaults')
    } catch {
      toast.error('Failed to reset configuration')
    } finally {
      setResetting(false)
    }
  }

  if (loading || !config) {
    return (
      <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center' }}>
        <Spinner size="md" />
      </div>
    )
  }

  const sizeListToStr = (arr: number[] | undefined) => (arr || []).join(', ')
  const strToSizeList = (s: string) => s.split(',').map((v) => parseFloat(v.trim())).filter((v) => !isNaN(v))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box', overflowY: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>
            Engineering Configuration
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
            Design methods, seismic frame types, connection standards, and material grades used by the build engine
          </p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={handleReset}
            disabled={resetting}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px', padding: '9px 16px',
              backgroundColor: 'transparent', border: '1px solid rgba(239,68,68,0.25)', borderRadius: '6px',
              color: '#EF4444', fontSize: '13px', fontWeight: 600, cursor: resetting ? 'not-allowed' : 'pointer',
            }}
          >
            <RotateCcw size={14} /> Reset All
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              display: 'flex', alignItems: 'center', gap: '8px', padding: '9px 20px',
              backgroundColor: '#3B82F6', border: 'none', borderRadius: '6px',
              color: '#FFFFFF', fontSize: '13px', fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer',
              boxShadow: '0 4px 14px rgba(59, 130, 246, 0.35)',
            }}
          >
            <Save size={14} /> {saving ? 'Saving...' : 'Apply'}
          </button>
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '760px', paddingBottom: '40px' }}>

        {/* Connection Design Method */}
        <div style={sectionStyle}>
          <h3 style={sectionTitleStyle}>Connection Design Method</h3>
          <div style={gridStyle}>
            <Field label="Design Method" badge={{ text: 'AI Recommended', color: '#8B5CF6' }}>
              <select value={get(['design_method'], 'ASD')} onChange={(e) => set(['design_method'], e.target.value)} style={selectStyle}>
                <option value="ASD">ASD (Allowable Strength Design) — Default</option>
                <option value="LRFD">LRFD (Load and Resistance Factor Design)</option>
              </select>
            </Field>
            <Field label="Beam End Reaction Calculation" help="How end reactions are derived when plan reactions aren't OCR-extracted yet.">
              <select value={get(['beam_end_reaction', 'mode'], 'udl')} onChange={(e) => set(['beam_end_reaction', 'mode'], e.target.value)} style={selectStyle}>
                <option value="udl">Auto-calculate from UDL</option>
                <option value="plan_reactions">Use Plan Reactions + Auto-calculate missing</option>
              </select>
            </Field>
            <Field label="UDL % of Tributary" help="Percentage of the assumed uniform design load applied to derive beam end reactions.">
              <input type="number" value={get(['beam_end_reaction', 'udl_percent'], 50)} onChange={(e) => set(['beam_end_reaction', 'udl_percent'], parseInt(e.target.value) || 0)} style={inputStyle} />
            </Field>
            <Field label="Assumed UDL (klf)">
              <input type="number" step="0.1" value={get(['beam_end_reaction', 'default_udl_klf'], 1.5)} onChange={(e) => set(['beam_end_reaction', 'default_udl_klf'], parseFloat(e.target.value) || 0)} style={inputStyle} />
            </Field>
          </div>
        </div>

        {/* Seismic Frame Type */}
        <div style={sectionStyle}>
          <h3 style={sectionTitleStyle}>Seismic Frame Type</h3>
          <div style={gridStyle}>
            <Field label="Moment Frame" badge={{ text: 'Default', color: '#3B82F6' }}>
              <select value={get(['seismic', 'moment_frame'], 'non_seismic')} onChange={(e) => set(['seismic', 'moment_frame'], e.target.value)} style={selectStyle}>
                <option value="non_seismic">Non-Seismic</option>
                <option value="ismf">Intermediate Steel Moment Frame (IMF)</option>
                <option value="smf">Special Moment Frame (SMF)</option>
              </select>
            </Field>
            <Field label="Brace Frame" badge={{ text: 'Beta', color: '#F59E0B' }}>
              <select value={get(['seismic', 'brace_frame'], 'non_seismic')} onChange={(e) => set(['seismic', 'brace_frame'], e.target.value)} style={selectStyle}>
                <option value="non_seismic">Non-Seismic</option>
                <option value="ocbf">OCBF — Ordinary Concentrically Braced Frame</option>
                <option value="scbf">SCBF — Special Concentrically Braced Frame</option>
                <option value="brb">BRB — Buckling Restrained Brace (Under Development)</option>
              </select>
            </Field>
          </div>
        </div>

        {/* Connection Types & Column Splice */}
        <div style={sectionStyle}>
          <h3 style={sectionTitleStyle}>Connection Type &amp; Column Splice</h3>
          <div style={gridStyle}>
            <Field label="Beam-Column Simple Connection" badge={{ text: 'Default', color: '#3B82F6' }}>
              <select value={get(['connection_types', 'beam_column'], 'bolted_double_angle')} onChange={(e) => set(['connection_types', 'beam_column'], e.target.value)} style={selectStyle}>
                <option value="bolted_double_angle">Bolted Double Angle</option>
                <option value="shear_tab">Shear Tab</option>
              </select>
            </Field>
            <Field label="Beam-Girder Connection">
              <select value={get(['connection_types', 'beam_girder'], 'bolted_double_angle')} onChange={(e) => set(['connection_types', 'beam_girder'], e.target.value)} style={selectStyle}>
                <option value="bolted_double_angle">Bolted Double Angle</option>
                <option value="shear_tab">Shear Tab</option>
              </select>
            </Field>
            <Field label="Column Splice Method" badge={{ text: 'Default', color: '#3B82F6' }}>
              <select value={get(['connection_types', 'column_splice_method'], 'welded_flange')} onChange={(e) => set(['connection_types', 'column_splice_method'], e.target.value)} style={selectStyle}>
                <option value="bolted_flange_inner_plate">Bolted Flange w/ Inner Plate</option>
                <option value="bolted_flange">Bolted Flange</option>
                <option value="welded_flange">Welded Flange</option>
                <option value="bolted_body">Only Bolted Body</option>
              </select>
            </Field>
            <Field label="Max Section Height Before Splice (ft)">
              <input type="number" step="0.1" value={get(['connection_types', 'max_splice_height_ft'], 35.0)} onChange={(e) => set(['connection_types', 'max_splice_height_ft'], parseFloat(e.target.value) || 0)} style={inputStyle} />
            </Field>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '14px', fontSize: '13px', color: '#F1F5F9', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={!!get(['connection_types', 'auto_splice'], false)}
              onChange={(e) => set(['connection_types', 'auto_splice'], e.target.checked)}
              style={{ cursor: 'pointer', width: '15px', height: '15px' }}
            />
            Auto Column Splicing — automatically split column stacks taller than the max height above
          </label>
        </div>

        {/* Material Settings */}
        <div style={sectionStyle}>
          <h3 style={sectionTitleStyle}>Material Settings — Structural Steel Grades</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
            {MATERIAL_ROWS.map(([key, label]) => (
              <Field key={key} label={label}>
                <input value={get(['materials', key], '')} onChange={(e) => set(['materials', key], e.target.value)} style={inputStyle} />
              </Field>
            ))}
          </div>
          <p style={{ fontSize: '11px', color: '#475569', marginTop: '12px', marginBottom: 0 }}>
            Additional plate types (Flat Bar, Continuity Plate, Doubler Plate, Gusset Plate, Stiffener Plate, Shear Tab Plate) are under development and use the Plate grade above until added.
          </p>
        </div>

        {/* Size Priorities */}
        <div style={sectionStyle}>
          <h3 style={sectionTitleStyle}>Size Priorities</h3>
          <p style={{ fontSize: '11px', color: '#64748B', margin: '0 0 14px' }}>
            Candidate sizes the connection design engine tries, in order, comma-separated (inches).
          </p>
          <div style={gridStyle}>
            <Field label="Shear Tab Thickness (in)">
              <input
                value={sizeListToStr(get(['size_priorities', 'shear_tab_thickness'], []))}
                onChange={(e) => set(['size_priorities', 'shear_tab_thickness'], strToSizeList(e.target.value))}
                style={inputStyle}
              />
            </Field>
            <Field label="Double Angle Thickness (in)">
              <input
                value={sizeListToStr(get(['size_priorities', 'double_angle_thickness'], []))}
                onChange={(e) => set(['size_priorities', 'double_angle_thickness'], strToSizeList(e.target.value))}
                style={inputStyle}
              />
            </Field>
            <Field label="Bolt Diameters (in)">
              <input
                value={sizeListToStr(get(['size_priorities', 'bolt_diameters'], []))}
                onChange={(e) => set(['size_priorities', 'bolt_diameters'], strToSizeList(e.target.value))}
                style={inputStyle}
              />
            </Field>
          </div>
        </div>

        {/* Labor Codes */}
        <div style={sectionStyle}>
          <h3 style={sectionTitleStyle}>Labor Codes</h3>
          <div style={gridStyle}>
            <Field label="Length Basis">
              <select value={get(['labor_codes', 'length_basis'], 'face_to_face')} onChange={(e) => set(['labor_codes', 'length_basis'], e.target.value)} style={selectStyle}>
                <option value="face_to_face">Face-to-Face</option>
                <option value="point_to_point">Point-to-Point</option>
              </select>
            </Field>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '14px', fontSize: '13px', color: '#F1F5F9', cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={!!get(['labor_codes', 'enabled'], true)}
              onChange={(e) => set(['labor_codes', 'enabled'], e.target.checked)}
              style={{ cursor: 'pointer', width: '15px', height: '15px' }}
            />
            Assign labor codes to BOM line items
          </label>
        </div>
      </div>
    </div>
  )
}
