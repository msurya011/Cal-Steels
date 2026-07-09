'use client'

import React from 'react'
import { AlertCircle } from 'lucide-react'

export default function ColumnsPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box' }}>
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>
          Column Groups & Splices
        </h1>
        <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
          Manage column stacks, elevation groupings, base plate designs, and splice offsets
        </p>
      </div>

      <div
        style={{
          flex: 1,
          border: '1px dashed rgba(59, 130, 246, 0.15)',
          borderRadius: '12px',
          backgroundColor: 'rgba(30, 41, 59, 0.15)',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '40px',
          textAlign: 'center',
        }}
      >
        <AlertCircle size={36} style={{ color: '#3B82F6', marginBottom: '16px' }} />
        <h3 style={{ margin: '0 0 8px', fontSize: '16px', fontWeight: 600, color: '#94A3B8' }}>
          Column Scheduler Module (Milestone M4)
        </h3>
        <p style={{ margin: 0, fontSize: '13px', color: '#475569', maxWidth: '400px', lineHeight: 1.5 }}>
          This interface is scheduled for Milestone M4. Once the connection design build engine is ready, column group stacks will automatically align to column grids and elevations.
        </p>
      </div>
    </div>
  )
}
