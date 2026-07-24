import React from 'react'
import { Columns, X } from 'lucide-react'

interface NavigationPanelProps {
  sidebarOpen: boolean
  setSidebarOpen: (open: boolean) => void
  leftTab: 'pages' | 'members'
  setLeftTab: (tab: 'pages' | 'members') => void
  membersCount: number
  pagesTabContent: React.ReactNode
  membersTabContent: React.ReactNode
}

export function NavigationPanel({
  sidebarOpen,
  setSidebarOpen,
  leftTab,
  setLeftTab,
  membersCount,
  pagesTabContent,
  membersTabContent,
}: NavigationPanelProps) {
  if (!sidebarOpen) return null

  return (
    <div
      style={{
        width: '320px', // slightly wider to accommodate the robust members list
        backgroundColor: '#0B1120',
        borderRight: '1px solid rgba(59, 130, 246, 0.1)',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        flexShrink: 0,
        boxShadow: '4px 0 15px rgba(0,0,0,0.2)'
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
          <X size={16} />
        </button>
      </div>

      {/* Capsule Segmented Tabs Control */}
      <div style={{ padding: '16px 16px 12px 16px', backgroundColor: '#0B1120' }}>
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
              backgroundColor: leftTab === 'pages' ? '#1E3A8A' : 'transparent',
              color: leftTab === 'pages' ? '#FFFFFF' : '#94A3B8',
              border: leftTab === 'pages' ? '1px solid rgba(59, 130, 246, 0.3)' : 'none',
              borderRadius: '20px',
              padding: '6px 12px',
              fontSize: '12px',
              fontWeight: 600,
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
              backgroundColor: leftTab === 'members' ? '#1E3A8A' : 'transparent',
              color: leftTab === 'members' ? '#FFFFFF' : '#94A3B8',
              border: leftTab === 'members' ? '1px solid rgba(59, 130, 246, 0.3)' : 'none',
              borderRadius: '20px',
              padding: '6px 12px',
              fontSize: '12px',
              fontWeight: 600,
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
                marginLeft: '8px',
                lineHeight: 1,
              }}
            >
              {membersCount}
            </span>
          </button>
        </div>
      </div>

      {/* Sidebar Content */}
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {leftTab === 'pages' ? pagesTabContent : membersTabContent}
      </div>
    </div>
  )
}
