'use client'

import React from 'react'
import { AlertCircle } from 'lucide-react'

export default function BracesPage() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box' }}>
      <div style={{ marginBottom: '24px' }}>
        <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>
          Braced Frames Scheduler
        </h1>
        <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
          Schedule vertical braced frames, diagonals, gussets design capacity, and frame elevations
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
          Braces Scheduler Module (Milestone M5)
        </h3>
        <p style={{ margin: 0, fontSize: '13px', color: '#475569', maxWidth: '400px', lineHeight: 1.5 }}>
          This scheduler panel is scheduled for Milestone M5. Brace grouping classification maps vertical diagonal planes across project grid lines.
        </p>
      </div>
    </div>
  )
}
