import React from 'react'

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg'
}

export function Spinner({ size = 'md' }: SpinnerProps) {
  const dimensions = {
    sm: '16px',
    md: '24px',
    lg: '36px',
  }[size]

  return (
    <div
      style={{
        display: 'inline-block',
        width: dimensions,
        height: dimensions,
        border: '3px solid rgba(59, 130, 246, 0.1)',
        borderTop: '3px solid #3B82F6',
        borderRadius: '50%',
        animation: 'spin 1s linear infinite',
      }}
    >
      <style>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  )
}
