'use client'

import React, { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { modelApi, drawingsApi } from '../../../../lib/api'
import { Spinner } from '../../../../components/ui/Spinner'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'
import { toast } from 'sonner'
import * as THREE from 'three'

interface ModelBeam {
  profile: string
  x1: number
  y1: number
  z1: number
  x2: number
  y2: number
  z2: number
  color?: string
}

interface ModelColumn {
  profile: string
  x: number
  y: number
  z_bottom: number
  z_top: number
  color?: string
}

interface ModelData {
  beams: ModelBeam[]
  columns: ModelColumn[]
}

export default function ThreeDModelPage() {
  const params = useParams()
  const projectId = params?.id as string
  const mountRef = useRef<HTMLDivElement>(null)
  const { selectedRatio } = useWorkspaceStore()

  const [loading, setLoading] = useState(true)
  const [pages, setPages] = useState<any[]>([])
  const [selectedPageId, setSelectedPageId] = useState('')

  // Load sheets to choose page
  useEffect(() => {
    if (!projectId) return
    drawingsApi
      .list(projectId)
      .then((drawings) => {
        if (drawings.length > 0) {
          return drawingsApi.listPages(drawings[0].id)
        }
        return []
      })
      .then((pgs) => {
        setPages(pgs)
        if (pgs.length > 0) {
          setSelectedPageId(pgs[0].id)
        } else {
          setLoading(false)
        }
      })
      .catch(() => {
        toast.error('Failed to load drawing sheets')
        setLoading(false)
      })
  }, [projectId])

  useEffect(() => {
    if (!selectedPageId) return
    setLoading(true)

    let activeScene = true
    let renderer: THREE.WebGLRenderer | null = null
    let animationFrameId: number
    let domElement: HTMLCanvasElement | null = null

    // Event listener references for clean removal
    let resizeHandler: (() => void) | null = null
    let mouseDownHandler: ((e: MouseEvent) => void) | null = null
    let mouseMoveHandler: ((e: MouseEvent) => void) | null = null
    let mouseUpHandler: (() => void) | null = null
    let wheelHandler: ((e: WheelEvent) => void) | null = null

    const load3DScene = async () => {
      try {
        const ratio = selectedRatio || 96
        const data = await modelApi.get(projectId, selectedPageId, ratio, 12)

        if (!activeScene) return
        setLoading(false)

        // Basic Three.js setup
        const scene = new THREE.Scene()
        scene.background = new THREE.Color('#090D1A')

        const width = mountRef.current?.clientWidth || 800
        const height = mountRef.current?.clientHeight || 600

        const camera = new THREE.PerspectiveCamera(45, width / height, 1, 1000)
        camera.position.set(0, 50, 100)

        renderer = new THREE.WebGLRenderer({ antialias: true })
        renderer.setSize(width, height)
        renderer.shadowMap.enabled = true
        domElement = renderer.domElement

        if (mountRef.current) {
          mountRef.current.innerHTML = ''
          mountRef.current.appendChild(domElement)
        }

        // Add lighting
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.6)
        scene.add(ambientLight)

        const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.8)
        dirLight1.position.set(50, 100, 50)
        scene.add(dirLight1)

        const dirLight2 = new THREE.DirectionalLight(0x3b82f6, 0.3)
        dirLight2.position.set(-50, -50, -50)
        scene.add(dirLight2)

        // Draw structural items
        // Columns (vertical bars)
        const columns = data.columns || []
        columns.forEach((col: any) => {
          const x = (col.x || 0) - 200 // Centering offset
          const z = (col.y || 0) - 200 // Swap Y/Z coordinates for Y-up alignment
          const bottom = col.z_bottom || 0
          const top = col.z_top || 14
          const height = top - bottom

          const geometry = new THREE.BoxGeometry(1.2, height, 1.2)
          const material = new THREE.MeshStandardMaterial({
            color: new THREE.Color(col.color || '#3B82F6'),
            roughness: 0.4,
            metalness: 0.8,
          })
          const mesh = new THREE.Mesh(geometry, material)
          mesh.position.set(x, bottom + height / 2, z)
          scene.add(mesh)
        })

        // Beams (horizontal spans)
        const beams = data.beams || []
        beams.forEach((beam: any) => {
          const x1 = (beam.x1 || 0) - 200
          const z1 = (beam.y1 || 0) - 200
          const y1 = beam.z1 || 12

          const x2 = (beam.x2 || 0) - 200
          const z2 = (beam.y2 || 0) - 200
          const y2 = beam.z2 || 12

          const dx = x2 - x1
          const dy = y2 - y1
          const dz = z2 - z1
          const distance = Math.sqrt(dx * dx + dy * dy + dz * dz)

          const geometry = new THREE.BoxGeometry(0.8, 0.8, distance)
          const material = new THREE.MeshStandardMaterial({
            color: new THREE.Color(beam.color || '#EC4899'),
            roughness: 0.4,
            metalness: 0.8,
          })
          const mesh = new THREE.Mesh(geometry, material)

          // Set position at midpoint
          mesh.position.set(x1 + dx / 2, y1 + dy / 2, z1 + dz / 2)

          // Rotate to line direction alignment
          mesh.lookAt(new THREE.Vector3(x2, y2, z2))

          scene.add(mesh)
        })

        // Grid boundaries reference guide lines
        const helper = new THREE.GridHelper(300, 30, '#1E293B', '#111827')
        helper.position.y = 0
        scene.add(helper)

        // Simple camera navigation rotate orbit state variables
        let isMouseDown = false
        let prevMousePos = { x: 0, y: 0 }
        let theta = 0.5 // horizontal rotation angle
        let phi = 1.0 // vertical rotation angle
        const radius = 120 // camera orbit radius

        const updateCameraPosition = () => {
          camera.position.x = radius * Math.sin(phi) * Math.sin(theta)
          camera.position.y = radius * Math.cos(phi)
          camera.position.z = radius * Math.sin(phi) * Math.cos(theta)
          camera.lookAt(0, 5, 0)
        }
        updateCameraPosition()

        // Setup custom Orbit interaction listeners
        const handleMouseDown = (e: MouseEvent) => {
          isMouseDown = true
          prevMousePos = { x: e.clientX, y: e.clientY }
        }

        const handleMouseMove = (e: MouseEvent) => {
          if (!isMouseDown) return
          const deltaX = e.clientX - prevMousePos.x
          const deltaY = e.clientY - prevMousePos.y
          prevMousePos = { x: e.clientX, y: e.clientY }

          theta -= deltaX * 0.01
          phi = Math.max(0.1, Math.min(Math.PI - 0.1, phi - deltaY * 0.01))
          updateCameraPosition()
        }

        const handleMouseUp = () => {
          isMouseDown = false
        }

        const handleWheel = (e: WheelEvent) => {
          camera.position.z += e.deltaY * 0.1
          camera.lookAt(0, 5, 0)
        }

        mouseDownHandler = handleMouseDown
        mouseMoveHandler = handleMouseMove
        mouseUpHandler = handleMouseUp
        wheelHandler = handleWheel

        domElement.addEventListener('mousedown', mouseDownHandler)
        window.addEventListener('mousemove', mouseMoveHandler)
        window.addEventListener('mouseup', mouseUpHandler)
        domElement.addEventListener('wheel', wheelHandler)

        // Resize handler
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

        // Animation Loop
        const animate = () => {
          animationFrameId = requestAnimationFrame(animate)
          if (renderer) renderer.render(scene, camera)
        }
        animate()

      } catch (err: any) {
        toast.error('Failed to construct 3D model representation')
        setLoading(false)
      }
    }

    load3DScene()

    return () => {
      activeScene = false
      if (animationFrameId) {
        cancelAnimationFrame(animationFrameId)
      }
      if (resizeHandler) {
        window.removeEventListener('resize', resizeHandler)
      }
      if (mouseMoveHandler) {
        window.removeEventListener('mousemove', mouseMoveHandler)
      }
      if (mouseUpHandler) {
        window.removeEventListener('mouseup', mouseUpHandler)
      }
      if (domElement) {
        if (mouseDownHandler) domElement.removeEventListener('mousedown', mouseDownHandler)
        if (wheelHandler) domElement.removeEventListener('wheel', wheelHandler)
        // Clean remove canvas to avoid React 'removeChild' error
        if (domElement.parentNode) {
          domElement.parentNode.removeChild(domElement)
        }
      }
      if (renderer) {
        renderer.dispose()
      }
    }
  }, [selectedPageId])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '24px', boxSizing: 'border-box' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px', flexWrap: 'wrap', gap: '12px' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: '20px', fontWeight: 700, color: '#F1F5F9' }}>
            3D Structural Model
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: '13px', color: '#64748B' }}>
            Interactive WebGL mockup rendered from extracted plan drawing data
          </p>
        </div>

        {/* Page selector */}
        {pages.length > 0 && (
          <select
            value={selectedPageId}
            onChange={(e) => setSelectedPageId(e.target.value)}
            style={{
              padding: '8px 12px',
              backgroundColor: '#111827',
              border: '1px solid rgba(59, 130, 246, 0.15)',
              borderRadius: '6px',
              color: '#F1F5F9',
              fontSize: '12px',
              outline: 'none',
            }}
          >
            {pages.map((p) => (
              <option key={p.id} value={p.id}>
                {p.sheet_no || `Page ${p.idx + 1}`}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Render Canvas Wrapper container */}
      <div
        ref={mountRef}
        style={{
          flex: 1,
          backgroundColor: '#090D1A',
          border: '1px solid rgba(59, 130, 246, 0.1)',
          borderRadius: '12px',
          overflow: 'hidden',
          position: 'relative',
          minHeight: '400px',
        }}
      >
        {loading && (
          <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(9, 13, 26, 0.8)', zIndex: 10 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px' }}>
              <Spinner size="md" />
              <span style={{ fontSize: '13px', color: '#94A3B8' }}>Assembling model...</span>
            </div>
          </div>
        )}
      </div>

      {/* Control instructions info */}
      <div style={{ marginTop: '12px', fontSize: '11px', color: '#475569', textAlign: 'center' }}>
        Drag with mouse to rotate perspective. Use scroll wheel to zoom model in/out.
      </div>
    </div>
  )
}
