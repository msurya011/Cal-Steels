import React, { useState, useMemo } from 'react'
import { Search, Eye, EyeOff, Target } from 'lucide-react'
import { MemberAccordion } from './MemberAccordion'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'

interface Member {
  id: string
  kind: string
  section: string | null
  status?: string
}

interface MembersTabProps {
  members: Member[]
  onClean?: () => void
  onBuild?: () => void
  isBuilding?: boolean
  activePage?: any
}

export function MembersTab({ members, onClean, onBuild, isBuilding, activePage }: MembersTabProps) {
  const { searchQuery, setSearchQuery, showAllMembers } = useWorkspaceStore()
  
  // Accordion expanded states
  const [expanded, setExpanded] = useState<Record<string, boolean>>({
    beams: false,
    columns: false,
    braces: false,
    joists: false,
  })

  const toggleExpand = (key: string) => {
    setExpanded((prev) => ({ ...prev, [key]: !prev[key] }))
  }

  // Filter members by search query
  const filteredMembers = useMemo(() => {
    if (!searchQuery) return members
    const q = searchQuery.toLowerCase()
    return members.filter((m) => {
      if (m.section && m.section.toLowerCase().includes(q)) return true
      if (m.status && m.status.toLowerCase().includes(q)) return true
      return false
    })
  }, [members, searchQuery])

  // Group by kind
  const beams = filteredMembers.filter((m) => m.kind === 'beam')
  const columns = filteredMembers.filter((m) => m.kind === 'column')
  const braces = filteredMembers.filter((m) => m.kind === 'vbrace' || m.kind === 'hbrace' || m.kind === 'brace')
  const joists = filteredMembers.filter((m) => m.kind === 'joist')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', backgroundColor: '#0B1120' }}>
      
      {/* Page Selector & Action Buttons */}
      <div style={{ padding: '0 16px 12px 16px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
        
        {/* Page Dropdown */}
        <select
          style={{
            width: '100%',
            backgroundColor: '#1E293B',
            color: '#F1F5F9',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '6px',
            fontSize: '13px',
            fontWeight: 600,
            padding: '8px 12px',
            outline: 'none',
          }}
          disabled
        >
          <option>{activePage ? activePage.title || `Page ${activePage.idx}` : 'No Page Selected'}</option>
        </select>

        {/* Clean / Build Buttons */}
        <div style={{ display: 'flex', gap: '8px' }}>
          <button
            onClick={onClean}
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              backgroundColor: 'rgba(239, 68, 68, 0.1)',
              color: '#EF4444',
              border: '1px solid rgba(239, 68, 68, 0.3)',
              borderRadius: '6px',
              padding: '6px 12px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            <span style={{ fontSize: '14px' }}>🗑</span> Clean
          </button>
          
          <button
            onClick={onBuild}
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: '6px',
              backgroundColor: 'rgba(16, 185, 129, 0.1)',
              color: '#10B981',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              borderRadius: '6px',
              padding: '6px 12px',
              fontSize: '13px',
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
            }}
          >
            <span style={{ fontSize: '14px' }}>▶</span> {isBuilding ? 'Building...' : 'Build'}
          </button>
        </div>
      </div>

      {/* Search Bar */}
      <div style={{ padding: '0 16px 12px 16px' }}>
        <div
          style={{
            position: 'relative',
            display: 'flex',
            alignItems: 'center',
            backgroundColor: '#1E293B',
            borderRadius: '6px',
            border: '1px solid rgba(255, 255, 255, 0.1)',
          }}
        >
          <Search size={14} color="#64748B" style={{ position: 'absolute', left: '10px' }} />
          <input
            type="text"
            placeholder="Search members (e.g. B_1, W12...)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              width: '100%',
              background: 'transparent',
              border: 'none',
              padding: '8px 10px 8px 32px',
              fontSize: '12px',
              color: '#F1F5F9',
              outline: 'none',
            }}
          />
        </div>
      </div>

      {/* Filters & Actions Bar */}
      <div style={{ display: 'flex', gap: '8px', padding: '0 16px 16px 16px', borderBottom: '1px solid rgba(255, 255, 255, 0.06)' }}>
        
        {/* Color Dropdown */}
        <select
          style={{
            flex: 1,
            backgroundColor: '#1E293B',
            color: '#94A3B8',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '6px',
            fontSize: '12px',
            padding: '6px 8px',
            outline: 'none',
          }}
        >
          <option value="status">Color: Status</option>
          <option value="kind">Color: Type</option>
        </select>

        {/* Isolate Button */}
        <button
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            backgroundColor: '#1E293B',
            color: '#94A3B8',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '6px',
            padding: '6px 10px',
            fontSize: '12px',
            cursor: 'pointer',
          }}
        >
          <Target size={14} />
          Isolate
        </button>

        {/* Show All Button */}
        <button
          onClick={showAllMembers}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            backgroundColor: '#1E293B',
            color: '#94A3B8',
            border: '1px solid rgba(255, 255, 255, 0.1)',
            borderRadius: '6px',
            padding: '6px 10px',
            fontSize: '12px',
            cursor: 'pointer',
          }}
        >
          <Eye size={14} />
          Show All
        </button>
      </div>

      {/* Accordions List */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px' }}>
        <MemberAccordion
          title="Beams"
          members={beams}
          isExpanded={expanded.beams}
          onToggleExpand={() => toggleExpand('beams')}
        />
        <MemberAccordion
          title="Columns"
          members={columns}
          isExpanded={expanded.columns}
          onToggleExpand={() => toggleExpand('columns')}
        />
        <MemberAccordion
          title="Braces"
          members={braces}
          isExpanded={expanded.braces}
          onToggleExpand={() => toggleExpand('braces')}
        />
        <MemberAccordion
          title="Joists"
          members={joists}
          isExpanded={expanded.joists}
          onToggleExpand={() => toggleExpand('joists')}
        />
      </div>

    </div>
  )
}
