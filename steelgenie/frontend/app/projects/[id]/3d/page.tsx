'use client'

import React from 'react'
import { useParams } from 'next/navigation'
import StructuralViewer3D from '../../../../components/StructuralViewer3D'

export default function ThreeDModelPage() {
  const params = useParams()
  const projectId = params?.id as string

  if (!projectId) return null

  return (
    <div style={{ height: '100%', width: '100%' }}>
      <StructuralViewer3D projectId={projectId} />
    </div>
  )
}
