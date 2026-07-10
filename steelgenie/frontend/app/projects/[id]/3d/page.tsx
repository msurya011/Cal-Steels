'use client'

import React, { useEffect, useRef, useState, useCallback } from 'react'
import { useParams } from 'next/navigation'
import { modelApi, drawingsApi } from '../../../../lib/api'
import { Spinner } from '../../../../components/ui/Spinner'
import { Box, Layers3 } from 'lucide-react'
import { toast } from 'sonner'
import * as THREE from 'three'

interface ModelMember {
  id: string
  type: string
  profile: string | null
  start: [number, number, number]
  end: [number, number, number]
}

type ColorMode = 'member_type' | 'building'

const TYPE_COLOR: Record<string, string> = {
  column: '#10B981',
  beam: '#EF4444',
  vbrace: '#3B82F6',
  hbrace: '#3B82F6',
  brace: '#3B82F6',
  joist: '#8B5CF6',
}
const BUILDING_COLOR = '#60A5FA'

const LEGEND_ITEMS = [
  { label: 'Columns', color: TYPE_COLOR.column },
  { label: 'Beams', color: TYPE_COLOR.beam },
  { label: 'Braces', color: TYPE_COLOR.vbrace },
  { label: 'Joists', color: TYPE_COLOR.joist },
]

export default function ThreeDModelPage() {
  const params = useParams()
  const projectId = params?.id as string
  const mountRef = useRef<HTMLDivElement>(null)
  const sceneObjectsRef = useRef<THREE.Mesh[]>([])

  const [loading, setLoading] = useState(true)
  const [hasBuiltPages, setHasBuiltPages] = useState<boolean | null>(null)
  const [members, setMembers] = useState<ModelMember[]>([])
  const [colorMode, setColorMode] = useState<ColorMode>('member_type')
  const [floorCount, setFloorCount] = useState(0)

  // ── Load + merge the 3D model across every built page in the project ──────
  const loadModel = useCallback(async () => {
    setLoading(true)
    try {
      const drawings = await drawingsApi.list(projectId)
      let allPages: any[] = []
      for (const d of drawings) {
        const pgs = await drawingsApi.listPages(d.id)
        allPages = allPages.concat(pgs)
      }
      allPages.sort((a, b) => (a.tos_ft ?? a.idx) - (b.tos_ft ?? b.idx))

      const builtPages = allPages.filter((p) => p.status === 'built')
      setHasBuiltPages(builtPages.length > 0)
      setFloorCount(builtPages.length)

      if (builtPages.length === 0) {
        setMembers([])
        setLoading(false)
        return
      }

      const merged: ModelMember[] = []
      for (const p of builtPages) {
        try {
          const ratio = p.scale_num || 96
          const data = await modelApi.get(projectId, p.id, ratio, 14)
          const pageMembers: ModelMember[] = (data.members || []).map((m: any) => ({
            id: `${p.id}_${m.id}`,
            type: m.type,
            profile: m.profile,
            start: m.start,
            end: m.end,
          }))
          merged.push(...pageMembers)
        } catch {
          // A single page failing to build a model shouldn't block the rest of the building.
        }
      }
      setMembers(merged)
    } catch {
      toast.error('Failed to load 3D model')
    } finally {
      setLoading(false)
    }
  }, [projectId])

  useEffect(() => {
    if (projectId) loadModel()
  }, [projectId, loadModel])

  // ── Render the merged member list into a Three.js scene ───────────────────
  useEffect(() => {
    if (!mountRef.current || members.length === 0) return

    let renderer: THREE.WebGLRenderer | null = null
    let animationFrameId: number
    let domElement: HTMLCanvasElement | null = null
    let resizeHandler: (() => void) | null = null
    let mouseDownHandler: ((e: MouseEvent) => void) | null = null
    let mouseMoveHandler: ((e: MouseEvent) => void) | null = null
    let mouseUpHandler: (() => void) | null = null
    let wheelHandler: ((e: WheelEvent) => void) | null = null

    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#090D1A')

    const width = mountRef.current.clientWidth || 800
    const height = mountRef.current.clientHeight || 600
    const camera = new THREE.PerspectiveCamera(45, width / height, 1, 2000)

    renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(width, height)
    domElement = renderer.domElement
    mountRef.current.innerHTML = ''
    mountRef.current.appendChild(domElement)

    scene.add(new THREE.AmbientLight(0xffffff, 0.6))
    const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.8)
    dirLight1.position.set(50, 100, 50)
    scene.add(dirLight1)
    const dirLight2 = new THREE.DirectionalLight(0x3b82f6, 0.3)
    dirLight2.position.set(-50, -50, -50)
    scene.add(dirLight2)

    // Bounding box across the whole merged building (X/Z plan extents), used to
    // center the model and size the camera orbit radius to fit it.
    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity, maxY = 0
    members.forEach((m) => {
      ;[m.start, m.end].forEach(([x, y, z]) => {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x)
        minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z)
        maxY = Math.max(maxY, y)
      })
    })
    const cx = (minX + maxX) / 2
    const cz = (minZ + maxZ) / 2
    const planSpan = Math.max(maxX - minX, maxZ - minZ, 20)
    const orbitRadius = Math.max(planSpan * 1.4, maxY * 2, 60)

    const meshes: THREE.Mesh[] = []
    members.forEach((m) => {
      const color = colorMode === 'building' ? BUILDING_COLOR : (TYPE_COLOR[m.type] || '#94A3B8')
      const material = new THREE.MeshStandardMaterial({ color: new THREE.Color(color), roughness: 0.4, metalness: 0.7 })

      if (m.type === 'column') {
        const [x1, y1, z1] = m.start
        const [, y2] = m.end
        const h = Math.max(0.5, Math.abs(y2 - y1))
        const geometry = new THREE.BoxGeometry(1.2, h, 1.2)
        const mesh = new THREE.Mesh(geometry, material)
        mesh.position.set(x1 - cx, Math.min(y1, y2) + h / 2, z1 - cz)
        scene.add(mesh)
        meshes.push(mesh)
      } else {
        const [x1, y1, z1] = m.start
        const [x2, y2, z2] = m.end
        const dx = x2 - x1, dy = y2 - y1, dz = z2 - z1
        const distance = Math.max(0.3, Math.sqrt(dx * dx + dy * dy + dz * dz))
        const thickness = m.type === 'joist' ? 0.5 : m.type.includes('brace') || m.type === 'brace' ? 0.6 : 0.8
        const geometry = new THREE.BoxGeometry(thickness, thickness, distance)
        const mesh = new THREE.Mesh(geometry, material)
        mesh.position.set(x1 + dx / 2 - cx, y1 + dy / 2, z1 + dz / 2 - cz)
        mesh.lookAt(new THREE.Vector3(x2 - cx, y2, z2 - cz))
        scene.add(mesh)
        meshes.push(mesh)
      }
    })
    sceneObjectsRef.current = meshes

    const helper = new THREE.GridHelper(Math.max(planSpan * 2, 60), 30, '#1E293B', '#111827')
    scene.add(helper)

    let isMouseDown = false
    let prevMousePos = { x: 0, y: 0 }
    let theta = 0.6
    let phi = 1.1
    let radius = orbitRadius

    const updateCameraPosition = () => {
      camera.position.x = radius * Math.sin(phi) * Math.sin(theta)
      camera.position.y = radius * Math.cos(phi) + maxY / 2
      camera.position.z = radius * Math.sin(phi) * Math.cos(theta)
      camera.lookAt(0, maxY / 2, 0)
    }
    updateCameraPosition()

    const handleMouseDown = (e: MouseEvent) => { isMouseDown = true; prevMousePos = { x: e.clientX, y: e.clientY } }
    const handleMouseMove = (e: MouseEvent) => {
      if (!isMouseDown) return
      const deltaX = e.clientX - prevMousePos.x
      const deltaY = e.clientY - prevMousePos.y
      prevMousePos = { x: e.clientX, y: e.clientY }
      theta -= deltaX * 0.01
      phi = Math.max(0.1, Math.min(Math.PI - 0.1, phi - deltaY * 0.01))
      updateCameraPosition()
    }
    const handleMouseUp = () => { isMouseDown = false }
    const handleWheel = (e: WheelEvent) => {
      radius = Math.max(10, radius + e.deltaY * 0.15)
      updateCameraPosition()
    }

    mouseDownHandler = handleMouseDown
    mouseMoveHandler = handleMouseMove
    mouseUpHandler = handleMouseUp
    wheelHandler = handleWheel
    domElement.addEventListener('mousedown', mouseDownHandler)
    window.addEventListener('mousemove', mouseMoveHandler)
    window.addEventListener('mouseup', mouseUpHandler)
    domElement.addEventListener('wheel', wheelHandler)

    const handleResize = () => {
      if (!mountRef.current || !renderer) return
      const w = mountRef.current.clientWidth
      const h = mountRef.current.clientHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    resizeHandler = handleResize
    window.addEventListener('resize', resizeHandler)

    const animate = () => {
      animationFrameId = requestAnimationFrame(animate)
      if (renderer) renderer.render(scene, camera)
    }
    animate()

    return () => {
      if (animationFrameId) cancelAnimationFrame(animationFrameId)
      if (resizeHandler) window.removeEventListener('resize', resizeHandler)
      if (mouseMoveHandler) window.removeEventListener('mousemove', mouseMoveHandler)
      if (mouseUpHandler) window.removeEventListener('mouseup', mouseUpHandler)
      if (domElement) {
        if (mouseDownHandler) domElement.removeEventListener('mousedown', mouseDownHandler)
        if (wheelHandler) domElement.removeEventListener('wheel', wheelHandler)
        if (domElement.parentNode) domElement.parentNode.removeChild(domElement)
      }
      if (renderer) renderer.dispose()
    }
  }, [members, colorMode])

  const containerStyle: React.CSSProperties = { display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box' }

  if (loading) {
    return (
      <div style={{ ...containerStyle, alignItems: 'center', justifyContent: 'center' }}>
        <Spinner size="md" />
      </div>
    )
  }

  if (!hasBuiltPages || members.length === 0) {
    return (
      <div style={containerStyle}>
        <div style={{ marginBottom: '20px' }}>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>3D Structural Model</h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>Whole-building model assembled from all built pages</p>
        </div>
        <div
          style={{
            flex: 1, border: '1px dashed rgba(59, 130, 246, 0.15)', borderRadius: '12px',
            backgroundColor: 'rgba(30, 41, 59, 0.15)', display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: '12px', padding: '40px', textAlign: 'center',
          }}
        >
          <Box size={40} style={{ color: '#3B82F6' }} />
          <h3 style={{ margin: 0, fontSize: '16px', fontWeight: 600, color: '#94A3B8' }}>Build a blueprint to view the model</h3>
          <p style={{ margin: 0, fontSize: '13px', color: '#475569', maxWidth: '420px', lineHeight: 1.5 }}>
            Once at least one page has been built, its members are assembled into this 3D view —
            columns stack floor-to-floor and beams/braces appear at each level automatically.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div style={containerStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>3D Structural Model</h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
            {floorCount} floor{floorCount === 1 ? '' : 's'} · {members.length} member{members.length === 1 ? '' : 's'}
          </p>
        </div>

        {/* Color mode toggle */}
        <div style={{ display: 'flex', backgroundColor: '#111827', border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '6px', padding: '3px' }}>
          {(['member_type', 'building'] as ColorMode[]).map((mode) => (
            <button
              key={mode}
              onClick={() => setColorMode(mode)}
              style={{
                display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 12px', borderRadius: '4px',
                border: 'none', cursor: 'pointer', fontSize: '12px', fontWeight: 600,
                backgroundColor: colorMode === mode ? '#3B82F6' : 'transparent',
                color: colorMode === mode ? '#fff' : '#94A3B8',
              }}
            >
              <Layers3 size={13} /> {mode === 'member_type' ? 'Member Type' : 'Building'}
            </button>
          ))}
        </div>
      </div>

      <div
        ref={mountRef}
        style={{
          flex: 1, backgroundColor: '#090D1A', border: '1px solid rgba(59, 130, 246, 0.1)',
          borderRadius: '12px', overflow: 'hidden', position: 'relative', minHeight: '400px',
        }}
      >
        {/* Legend */}
        {colorMode === 'member_type' && (
          <div
            style={{
              position: 'absolute', bottom: '16px', left: '16px', backgroundColor: 'rgba(17, 24, 39, 0.85)',
              border: '1px solid rgba(59, 130, 246, 0.15)', borderRadius: '8px', padding: '10px 14px',
              display: 'flex', flexDirection: 'column', gap: '6px', zIndex: 5,
            }}
          >
            {LEGEND_ITEMS.map((item) => (
              <div key={item.label} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', color: '#CBD5E1' }}>
                <span style={{ width: '10px', height: '10px', borderRadius: '2px', backgroundColor: item.color, display: 'inline-block' }} />
                {item.label}
              </div>
            ))}
          </div>
        )}
      </div>

      <div style={{ marginTop: '10px', fontSize: '11px', color: '#475569', textAlign: 'center' }}>
        Drag to rotate · scroll to zoom
      </div>
    </div>
  )
}
