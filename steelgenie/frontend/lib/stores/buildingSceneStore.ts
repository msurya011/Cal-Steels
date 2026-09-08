/**
 * buildingSceneStore.ts
 * ─────────────────────
 * Persistent Three.js scene store for the 3D structural model.
 *
 * Architecture invariant: ONE scene per project. The scene is never reset
 * when members are added — only appended to. Full rebuilds only happen when
 * explicitly requested (scope/colorMode change or user clicks "Rebuild").
 *
 * Implements the plan from implementation_plan.md:
 *  Phase 2 – Persistent scene with incremental append
 *  Phase 3 – O(1) selection highlight via buffer swap
 *  Phase 4 – SpatialGrid for O(N) dedup + dirty-flag animation loop
 */

import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'

// ─── Types ────────────────────────────────────────────────────────────────────

export interface RawMember {
  id: string
  member_id: string
  page_id: string
  type: string
  profile: string | null
  piecemark: string | null
  status: string | null
  start: [number, number, number]
  end: [number, number, number]
  unlabeled?: boolean
  merged_member_ids?: string[]
  floor_id?: string
  floor_name?: string
  // Post-Build fabrication attributes (see backend attach_bom_attributes) --
  // null until the project's Build step has run, since that's the engine
  // that actually computes them. Only weight_lbs is real today; sequence/
  // labor_code/paint are carried through so the UI can honestly show "no
  // data yet" for those color-by modes instead of pretending.
  weight_lbs?: number | null
  sequence?: number | null
  labor_code?: string | null
  paint?: string | null
}

export interface RawGridLine {
  id: string
  axis: 'x' | 'y'
  label: string
  page_id: string
  start: [number, number, number]
  end: [number, number, number]
}

export interface SceneMember {
  globalId: string          // stable deduplicated ID (first member_id wins)
  memberIds: string[]       // all raw member_ids merged here
  pageIds: string[]         // all source page_ids
  x1: number; z1: number
  x2: number; z2: number
  // Real per-endpoint height in feet, straight from the backend's merged
  // model (floor elevation_ft for beams/braces, base->TOS span for
  // columns). Previously these were computed but silently thrown away --
  // every member was written into the render buffer at Y=0 regardless of
  // which floor it belonged to, so a multi-floor building rendered as one
  // flat plan sheet instead of a stacked 3D building.
  y1: number; y2: number
  elevation: number         // TOS ft
  type: string
  profile: string | null
  piecemark: string | null
  unlabeled: boolean
  floorId: string | null
  floorName: string | null
  colorGroupKey: string     // color hex used as buffer bucket key
  bufferIndex: number       // index in its ColorGroup buffer (segment index)
  status: string | null
  weight_lbs: number | null
  sequence: number | null
  labor_code: string | null
  paint: string | null
  mesh?: THREE.Mesh
}

interface ColorGroup {
  positions: Float32Array
  capacity: number          // in members (each = 6 floats)
  count: number
  lineSegs: THREE.LineSegments
}

// ─── Spatial Grid for O(N) proximity queries ──────────────────────────────────

class SpatialGrid {
  private cells = new Map<string, SceneMember[]>()
  private cellSize: number

  constructor(cellSize = 2.0) { this.cellSize = cellSize }

  private key(xi: number, zi: number): string { return `${xi},${zi}` }
  private cellOf(v: number): number { return Math.floor(v / this.cellSize) }

  insert(m: SceneMember) {
    const x1i = this.cellOf(m.x1), x2i = this.cellOf(m.x2)
    const z1i = this.cellOf(m.z1), z2i = this.cellOf(m.z2)
    const minXi = Math.min(x1i, x2i), maxXi = Math.max(x1i, x2i)
    const minZi = Math.min(z1i, z2i), maxZi = Math.max(z1i, z2i)
    for (let xi = minXi; xi <= maxXi; xi++) {
      for (let zi = minZi; zi <= maxZi; zi++) {
        const k = this.key(xi, zi)
        if (!this.cells.has(k)) this.cells.set(k, [])
        this.cells.get(k)!.push(m)
      }
    }
  }

  removeFromCell(m: SceneMember) {
    // Remove m from all cells it was inserted into
    const x1i = this.cellOf(m.x1), x2i = this.cellOf(m.x2)
    const z1i = this.cellOf(m.z1), z2i = this.cellOf(m.z2)
    const minXi = Math.min(x1i, x2i), maxXi = Math.max(x1i, x2i)
    const minZi = Math.min(z1i, z2i), maxZi = Math.max(z1i, z2i)
    for (let xi = minXi; xi <= maxXi; xi++) {
      for (let zi = minZi; zi <= maxZi; zi++) {
        const k = this.key(xi, zi)
        const arr = this.cells.get(k)
        if (arr) {
          const idx = arr.indexOf(m)
          if (idx !== -1) arr.splice(idx, 1)
        }
      }
    }
  }

  findNear(x: number, z: number, radius: number): SceneMember[] {
    const ri = Math.ceil(radius / this.cellSize)
    const xi = this.cellOf(x), zi = this.cellOf(z)
    const result = new Set<SceneMember>()
    for (let dx = -ri; dx <= ri; dx++) {
      for (let dz = -ri; dz <= ri; dz++) {
        for (const m of this.cells.get(this.key(xi + dx, zi + dz)) || []) {
          result.add(m)
        }
      }
    }
    return [...result]
  }

  clear() { this.cells.clear() }
}

// ─── Color helper ─────────────────────────────────────────────────────────────

// Matches the reference product's steel/blue material palette: beams render
// as brushed-steel silver (the actual material color of a rolled shape),
// columns as blue -- distinct from braces (amber) and joists (purple) so all
// four member types stay visually separable in Member Type color mode.
// Beam color was a pale silver (#9CA6B3) that, combined with the new
// metallic material + room-environment reflections, blew out to near-white
// on every top face catching the key light -- reading as washed-out, not
// steel. A dark red-oxide/primer brown is both the actual real-world color
// most structural steel ships in (shop primer coat) and what the reference
// product's renders show, so it also reads as "steel" at a glance instead
// of "generic pale gray blocks."
export const TYPE_COLOR: Record<string, string> = {
  column:  '#2563EB',
  beam:    '#6B3A2E',
  vbrace:  '#F59E0B',
  hbrace:  '#F59E0B',
  brace:   '#F59E0B',
  joist:   '#7C3AED',
}
export const UNLABELED_BEAM_COLOR = '#8B8F99'
export const BUILDING_COLOR       = '#3B82F6'
export const SELECTION_COLOR      = '#00FF00'
export const NO_DATA_COLOR        = '#475569' // used by Weight/Sequence/Labor Code/Paint when a member has no such data yet (pre-Build)

// SteelGenie's "color by" menu: Member Type, Status, Sequence, Weight,
// Labor Code, Paint. "Building" is a CalSteel-only bonus mode (flat color,
// useful for silhouette review) kept alongside them.
export type ColorMode = 'member_type' | 'status' | 'sequence' | 'weight' | 'labor_code' | 'paint' | 'building'

export const STATUS_COLOR_FOR_LEGEND: Record<string, string> = {
  verified:    '#10B981',
  active:      '#3B82F6',
  need_review: '#F59E0B',
  rejected:    '#EF4444',
  excluded:    '#64748B',
}

const STATUS_COLOR: Record<string, string> = {
  verified:     '#10B981',
  active:       '#3B82F6',
  need_review:  '#F59E0B',
  rejected:     '#EF4444',
  excluded:     '#64748B',
}

// Small deterministic string->color hash for categorical fields with no
// fixed palette (labor code, paint spec) -- same string always gets the
// same color within a session, distinct strings spread across hues.
const HASH_PALETTE = ['#3B82F6', '#F59E0B', '#10B981', '#EC4899', '#8B5CF6', '#06B6D4', '#F97316', '#84CC16', '#EF4444', '#14B8A6']
function hashColor(value: string): string {
  let h = 0
  for (let i = 0; i < value.length; i++) h = (h * 31 + value.charCodeAt(i)) >>> 0
  return HASH_PALETTE[h % HASH_PALETTE.length]
}

// Weight gradient: light amber (light member) -> deep red (heavy member).
// Range is a reasonable structural-steel span (0-2000 lb piece) rather than
// computed per-project min/max, so color meaning stays stable as you scope
// in and out of floors/sheets.
function weightColor(lbs: number): string {
  const t = Math.max(0, Math.min(1, lbs / 2000))
  const r = Math.round(253 - t * (253 - 153))
  const g = Math.round(230 - t * (230 - 27))
  const b = Math.round(138 - t * (138 - 27))
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`
}

// ─── Real cross-section sizing ─────────────────────────────────────────────
// Members were previously rendered as 1px THREE.Line segments -- wireframe,
// not steel. SteelGenie renders solid extruded members with real
// proportions. This parses the AISC designation (falls back to sane
// per-kind defaults when a member has no profile yet) so the 3D box each
// member gets is actually sized like the shape it represents, not a
// generic blob.
export function profileBoxDims(kind: string, profile: string | null): { depthFt: number; widthFt: number } {
  const p = (profile || '').toUpperCase().trim()

  // HSS/box tube: HSS8X8X1/2, HSS6X4X3/8 -- depth x width x wall
  let m = p.match(/^HSS(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)X/)
  if (m) return { depthFt: parseFloat(m[1]) / 12, widthFt: parseFloat(m[2]) / 12 }

  // Pipe: PIPE6, PIPE8XXS -- round, treat as square-equivalent for the box proxy
  m = p.match(/^PIPE(\d+(?:\.\d+)?)/)
  if (m) { const d = parseFloat(m[1]) / 12; return { depthFt: d, widthFt: d } }

  // Wide-flange / channel / angle families: W12X26, C10X15.3, MC8X8.5, S12X31.8
  m = p.match(/^(W|C|MC|S|HP|WT|MT|ST|M)(\d+(?:\.\d+)?)X(\d+(?:\.\d+)?)/)
  if (m) {
    const nominalDepthFt = parseFloat(m[2]) / 12
    // Flange/leg width isn't in the designation (that's the weight, not a
    // dimension) -- use the standard rule-of-thumb proportion for rolled
    // shapes rather than inventing a fixed number.
    return { depthFt: nominalDepthFt, widthFt: nominalDepthFt * 0.4 }
  }

  // No profile yet (pre-classification) -- reasonable per-kind defaults so
  // the model still reads as "columns are chunkier than braces" even before
  // a real section is assigned.
  if (kind === 'column') return { depthFt: 0.75, widthFt: 0.75 }
  if (kind === 'joist') return { depthFt: 0.5, widthFt: 0.2 }
  if (kind === 'vbrace' || kind === 'hbrace' || kind === 'brace') return { depthFt: 0.35, widthFt: 0.2 }
  return { depthFt: 0.8, widthFt: 0.35 } // beam default
}

export function getMemberColor(m: RawMember | SceneMember, colorMode: ColorMode, selectedId: string | null): string {
  const memberIds = 'memberIds' in m ? m.memberIds : [m.member_id, ...(m.merged_member_ids || [])]
  if (selectedId && memberIds.includes(selectedId)) return SELECTION_COLOR

  if (colorMode === 'building') return BUILDING_COLOR

  if (colorMode === 'status') {
    const status = m.status
    return (status && STATUS_COLOR[status]) || NO_DATA_COLOR
  }

  if (colorMode === 'weight') {
    const w = m.weight_lbs
    return w != null ? weightColor(w) : NO_DATA_COLOR
  }

  if (colorMode === 'sequence') {
    const seq = m.sequence
    return seq != null ? hashColor(String(seq)) : NO_DATA_COLOR
  }

  if (colorMode === 'labor_code') {
    const code = m.labor_code
    return code ? hashColor(code) : NO_DATA_COLOR
  }

  if (colorMode === 'paint') {
    const paint = m.paint
    return paint ? hashColor(paint) : NO_DATA_COLOR
  }

  // member_type (default)
  if (m.type === 'column') return TYPE_COLOR.column
  if (m.type === 'joist')  return TYPE_COLOR.joist
  if (m.type === 'vbrace' || m.type === 'hbrace' || m.type === 'brace') return TYPE_COLOR.vbrace
  if (m.type === 'beam')   return ('unlabeled' in m ? m.unlabeled : (m as RawMember).unlabeled) ? UNLABELED_BEAM_COLOR : TYPE_COLOR.beam
  return TYPE_COLOR.beam
}

// ─── Store state (module-level, survives React re-renders) ────────────────────

const INITIAL_CAPACITY = 512
const GROW_FACTOR = 2

export type ProjectionMode = 'orthographic' | 'perspective'
export type CameraPreset = 'top' | 'front' | 'back' | 'left' | 'right' | 'home' | 'ne_iso' | 'nw_iso'

const DEG = Math.PI / 180
// Classic isometric tilt (atan(1/sqrt(2))) — matches the "Home"/"NE Iso"/"NW Iso" presets.
const ISO_ELEVATION = Math.atan(1 / Math.SQRT2)
const CAMERA_PRESETS: Record<CameraPreset, { azimuth: number; elevation: number }> = {
  top:    { azimuth: 0,        elevation: 89 * DEG },
  front:  { azimuth: 0,        elevation: 0 },
  back:   { azimuth: 180 * DEG, elevation: 0 },
  left:   { azimuth: 90 * DEG,  elevation: 0 },
  right:  { azimuth: -90 * DEG, elevation: 0 },
  home:   { azimuth: 45 * DEG,  elevation: ISO_ELEVATION },
  ne_iso: { azimuth: 45 * DEG,  elevation: ISO_ELEVATION },
  nw_iso: { azimuth: 135 * DEG, elevation: ISO_ELEVATION },
}

class BuildingSceneStore {
  // Three.js objects — both camera types are kept alive at all times so
  // switching Perspective <-> Orthographic is instant; `camera` always
  // points at whichever one is currently active and is what actually gets
  // rendered / raycast against.
  scene:    THREE.Scene | null = null
  camera:   THREE.OrthographicCamera | THREE.PerspectiveCamera | null = null
  orthoCam: THREE.OrthographicCamera | null = null
  perspCam: THREE.PerspectiveCamera | null = null
  renderer: THREE.WebGLRenderer | null = null
  container: HTMLDivElement | null = null
  raycaster = new THREE.Raycaster()
  groundPlane = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)

  // Orbit camera state. The model is a flat XZ wireframe (see _writeSegment
  // — every vertex is Y=0, since the extraction pipeline doesn't produce
  // real per-member elevation data yet), so there's nothing to fake by
  // pretending floors are stacked in Y. What orbit DOES give us honestly is
  // the same camera behavior as the reference product: Top/Front/Iso/etc.
  // presets and free rotation around the flat plan, which is exactly what
  // its own "3D" view looks like for a single/near-flat floor too.
  projectionMode: ProjectionMode = 'orthographic'
  orbitAzimuth   = CAMERA_PRESETS.home.azimuth
  orbitElevation = CAMERA_PRESETS.home.elevation
  orbitDistance  = 150

  // Data
  members          = new Map<string, SceneMember>()   // globalId → SceneMember
  memberIdToGlobal = new Map<string, string>()         // raw member_id → globalId
  grids            = new Map<string, RawGridLine>()    // grid id → RawGridLine
  colorGroups      = new Map<string, ColorGroup>()     // colorHex → ColorGroup
  gridGroup        = new THREE.Group()
  columnGroup:     THREE.LineSegments | null = null
  groundMesh:      THREE.Mesh | null = null
  envMap:          THREE.Texture | null = null

  // Tracking
  pageLoadedSet    = new Set<string>()
  spatialGrid      = new SpatialGrid(2.0)

  // Rendering state
  colorMode:       ColorMode = 'member_type'
  selectedId:      string | null = null
  selectedIds:     Set<string> = new Set()
  panX = 0; panY = 0; panZ = 0
  viewHalfW = 100; viewHalfH = 75
  zoom = 1.0
  animFrameId:     number | null = null
  dirty = false

  // Camera interaction
  isMouseDown = false
  dragged     = false
  prevMouse   = { x: 0, y: 0 }

  // Listeners for component re-render
  private listeners: Array<() => void> = []

  subscribe(fn: () => void) {
    this.listeners.push(fn)
    return () => { this.listeners = this.listeners.filter(l => l !== fn) }
  }
  notify() { this.listeners.forEach(fn => fn()) }
  markDirty() { this.dirty = true }

  // ── Scene initialization ──────────────────────────────────────────────────

  initScene(container: HTMLDivElement, projectId: string) {
    // Reuse existing scene for same project (incremental mode)
    if (this.scene && this.renderer && this.container === container) {
      this.markDirty()
      return
    }

    this.destroyScene()
    this.container = container

    const scene = new THREE.Scene()
    scene.background = new THREE.Color('#F1F5F9')
    this.scene = scene
    scene.add(this.gridGroup)
    for (const group of this.colorGroups.values()) {
      scene.add(group.lineSegs)
    }
    for (const m of this.members.values()) {
      // destroyScene() disposes+deletes every member's solid mesh (GPU
      // resources tied to the old WebGL context can't outlive it). If this
      // is a re-init on the same data (tab switch, route remount, React
      // strict-mode double effect), m.mesh is gone even though m itself
      // still has everything needed to rebuild it -- regenerate rather
      // than silently rendering wireframe-only for the rest of the session.
      if (!m.mesh) {
        m.mesh = this._createSolidMesh(m, m.colorGroupKey)
      }
      scene.add(m.mesh)
    }

    // Large flat ground plane -- the reference product always shows the
    // building sitting on a real ground surface, which reads as "a real
    // building" instantly even before you look at the steel itself. We only
    // had grid *lines* floating in space with nothing under them, which is
    // part of why the result read as a sketch rather than a solid model.
    // Fixed oversized plane (20,000ft) rather than one sized to the current
    // model, so it always reads as "ground extending to the horizon"
    // regardless of building size, and never needs resizing as members load.
    const groundGeo = new THREE.PlaneGeometry(20000, 20000)
    const groundMat = new THREE.MeshStandardMaterial({ color: '#E8ECF1', roughness: 0.95, metalness: 0.0 })
    const ground = new THREE.Mesh(groundGeo, groundMat)
    ground.rotation.x = -Math.PI / 2
    ground.position.y = -0.05 // a hair below y=0 so grid lines/column bases don't z-fight with it
    ground.receiveShadow = true
    this.groundMesh = ground
    scene.add(ground)

    // Lighting tuned for a visible steel material look (defined highlight +
    // shadow side per face, like the reference's brushed-metal beams)
    // instead of the flat, shadowless "everything is the same brightness"
    // look a single soft ambient light gives every box.
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.45)
    scene.add(ambientLight)

    const dirLight1 = new THREE.DirectionalLight(0xffffff, 0.9)
    dirLight1.position.set(150, 400, 200)
    scene.add(dirLight1)

    const dirLight2 = new THREE.DirectionalLight(0xffffff, 0.35)
    dirLight2.position.set(-150, 250, -150)
    scene.add(dirLight2)

    // Soft light from below/behind so the underside of beams and joists
    // (visible from an isometric angle) isn't pure black -- steel photographs
    // with some bounce light even in shadow, and this reads much closer to
    // the reference's evenly-lit-but-still-shaded members.
    const fillLight = new THREE.DirectionalLight(0xffffff, 0.2)
    fillLight.position.set(0, -100, 300)
    scene.add(fillLight)

    const w = container.clientWidth || 800
    const h = container.clientHeight || 600
    this.orthoCam = new THREE.OrthographicCamera(-100, 100, 75, -75, -1000, 1000)
    this.perspCam = new THREE.PerspectiveCamera(45, w / h, 0.1, 5000)
    this.camera = this.projectionMode === 'orthographic' ? this.orthoCam : this.perspCam
    this._applyCamera()

    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(window.devicePixelRatio)
    renderer.setSize(w, h)
    this.renderer = renderer

    // Metalness alone doesn't read as "steel" without something for it to
    // reflect -- MeshStandardMaterial's specular response needs either a
    // real environment map or it just looks like flat matte plastic no
    // matter how high metalness is set. A neutral studio-room environment
    // (soft gradient walls/ceiling, no visible geometry of its own) gives
    // every beam/column a believable metallic sheen and highlight without
    // needing an actual HDRI asset shipped with the app.
    const pmrem = new THREE.PMREMGenerator(renderer)
    this.envMap = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
    scene.environment = this.envMap
    pmrem.dispose()

    container.innerHTML = ''
    container.appendChild(renderer.domElement)

    this._startAnimationLoop()
  }

  private _startAnimationLoop() {
    if (this.animFrameId !== null) return
    const loop = () => {
      this.animFrameId = requestAnimationFrame(loop)
      if (this.dirty && this.renderer && this.scene && this.camera) {
        this.renderer.render(this.scene, this.camera)
        this.dirty = false
      }
    }
    loop()
  }

  destroyScene() {
    if (this.animFrameId !== null) {
      cancelAnimationFrame(this.animFrameId)
      this.animFrameId = null
    }
    if (this.renderer) {
      this.renderer.domElement.parentNode?.removeChild(this.renderer.domElement)
      this.renderer.dispose()
      this.renderer = null
    }
    // Dispose existing solid meshes
    for (const m of this.members.values()) {
      if (m.mesh) {
        m.mesh.geometry.dispose()
        if (Array.isArray(m.mesh.material)) {
          m.mesh.material.forEach(mat => mat.dispose())
        } else {
          m.mesh.material.dispose()
        }
        delete m.mesh
      }
    }
    if (this.groundMesh) {
      this.groundMesh.geometry.dispose()
      ;(this.groundMesh.material as THREE.Material).dispose()
      this.groundMesh = null
    }
    if (this.envMap) {
      this.envMap.dispose()
      this.envMap = null
    }
    this.scene = null
    this.camera = null
    this.orthoCam = null
    this.perspCam = null
    this.container = null
    this.dirty = false
  }

  // ── Color group buffer management ─────────────────────────────────────────

  private _getOrCreateGroup(colorHex: string): ColorGroup {
    if (this.colorGroups.has(colorHex)) return this.colorGroups.get(colorHex)!

    const capacity = INITIAL_CAPACITY
    const positions = new Float32Array(capacity * 6)
    const geo = new THREE.BufferGeometry()
    const attr = new THREE.BufferAttribute(positions, 3)
    attr.setUsage(THREE.DynamicDrawUsage)
    geo.setAttribute('position', attr)
    geo.setDrawRange(0, 0)

    const mat = new THREE.LineBasicMaterial({ color: new THREE.Color(colorHex) })
    const lineSegs = new THREE.LineSegments(geo, mat)

    const group: ColorGroup = { positions, capacity, count: 0, lineSegs }
    this.colorGroups.set(colorHex, group)
    this.scene?.add(lineSegs)
    return group
  }

  private _growGroup(group: ColorGroup) {
    const newCapacity = group.capacity * GROW_FACTOR
    const newPositions = new Float32Array(newCapacity * 6)
    newPositions.set(group.positions)
    group.positions = newPositions
    group.capacity = newCapacity

    const geo = group.lineSegs.geometry
    geo.setAttribute('position', new THREE.BufferAttribute(newPositions, 3))
    ;(geo.attributes.position as THREE.BufferAttribute).setUsage(THREE.DynamicDrawUsage)
  }

  private _writeSegment(group: ColorGroup, index: number, x1: number, y1: number, z1: number, x2: number, y2: number, z2: number) {
    const base = index * 6
    group.positions[base + 0] = x1; group.positions[base + 1] = y1; group.positions[base + 2] = z1
    group.positions[base + 3] = x2; group.positions[base + 4] = y2; group.positions[base + 5] = z2
  }

  private _flushGroup(group: ColorGroup) {
    const attr = group.lineSegs.geometry.attributes.position as THREE.BufferAttribute
    attr.needsUpdate = true
    group.lineSegs.geometry.setDrawRange(0, group.count * 2)
    this.markDirty()
  }

  // ── Member management ────────────────────────────────────────────────────

  // A box with a flat gray material reads as "a placeholder block," not
  // steel -- there's no flange to catch light, no web shadow line, nothing
  // for the eye to recognize as a rolled shape. Real W/HP/M/S sections are
  // an I-profile (two flanges + a web); this builds that actual cross-
  // section and extrudes it along the member's length instead of using a
  // solid rectangular box, matching the flange lines visible on every beam
  // in the reference product's renders. HSS/pipe/channel/angle sections and
  // anything unclassified keep the box (a box already IS the right shape
  // for a tube; a wrong I-shape for those would be worse, not better).
  private _isWideFlange(profile: string | null): boolean {
    const p = (profile || '').toUpperCase().trim()
    return /^(W|HP|M|S)\d/.test(p)
  }

  // 2D I-shape centered on the origin, sized to the member's real nominal
  // depth/flange-width, with flange/web thickness estimated as a standard
  // rule-of-thumb proportion of the depth (AISC designations only encode
  // nominal depth + weight, not flange/web thickness, so there's no exact
  // value to read -- this is the same "reasonable proportion, not invented
  // geometry" approach profileBoxDims already uses for flange width).
  private _iBeamShape(crossDepth: number, crossWidth: number): THREE.Shape {
    const hd = crossDepth / 2
    const hw = crossWidth / 2
    const tf = Math.min(hd * 0.6, Math.max(0.02, crossDepth * 0.09))  // flange thickness
    const tw = Math.min(hw * 0.6, Math.max(0.015, crossDepth * 0.045)) // web thickness
    const htw = tw / 2

    const shape = new THREE.Shape()
    shape.moveTo(-hw, hd)
    shape.lineTo(hw, hd)
    shape.lineTo(hw, hd - tf)
    shape.lineTo(htw, hd - tf)
    shape.lineTo(htw, -hd + tf)
    shape.lineTo(hw, -hd + tf)
    shape.lineTo(hw, -hd)
    shape.lineTo(-hw, -hd)
    shape.lineTo(-hw, -hd + tf)
    shape.lineTo(-htw, -hd + tf)
    shape.lineTo(-htw, hd - tf)
    shape.lineTo(-hw, hd - tf)
    shape.closePath()
    return shape
  }

  // Extrudes the I-shape along +Z by `length`, then recenters it on Z so it
  // matches BoxGeometry's centered-at-origin convention (the rest of this
  // class positions meshes assuming the geometry's own origin is its
  // midpoint, e.g. `mesh.position.copy(startVec).add(direction * 0.5)`).
  private _iBeamGeometry(crossDepth: number, crossWidth: number, length: number): THREE.BufferGeometry {
    const shape = this._iBeamShape(crossDepth, crossWidth)
    const geom = new THREE.ExtrudeGeometry(shape, { depth: Math.max(0.01, length), bevelEnabled: false, steps: 1 })
    geom.translate(0, 0, -length / 2)
    return geom
  }

  private _createSolidMesh(m: SceneMember, colorHex: string): THREE.Mesh {
    const startVec = new THREE.Vector3(m.x1, m.y1, m.z1)
    const endVec = new THREE.Vector3(m.x2, m.y2, m.z2)
    const direction = new THREE.Vector3().subVectors(endVec, startVec)
    const length = direction.length()

    // Real AISC-derived proportions (W12X26 renders like a 12" member, an
    // HSS8X8 renders like an 8" tube, etc.) instead of one generic box size
    // for every beam regardless of what section it actually is.
    const { depthFt, widthFt } = profileBoxDims(m.type, m.profile)
    let width = widthFt
    let height = depthFt
    let depth = length

    let setbackStart = 0.25
    let setbackEnd = 0.25

    if (m.type === 'beam' || m.type === 'joist') {
      const nearStart = this.spatialGrid.findNear(m.x1, m.z1, 2.5)
      const colStart = nearStart.find(n => n.type === 'column' && (n.y1 <= m.y1 + 1.5 && n.y2 >= m.y1 - 1.5))
      if (colStart) {
        const cDims = profileBoxDims('column', colStart.profile)
        const colRadius = Math.max(cDims.depthFt, cDims.widthFt) / 2
        setbackStart = Math.min(length * 0.35, colRadius + 0.04)
      } else {
        setbackStart = Math.min(length * 0.25, 0.25)
      }

      const nearEnd = this.spatialGrid.findNear(m.x2, m.z2, 2.5)
      const colEnd = nearEnd.find(n => n.type === 'column' && (n.y1 <= m.y2 + 1.5 && n.y2 >= m.y2 - 1.5))
      if (colEnd) {
        const cDims = profileBoxDims('column', colEnd.profile)
        const colRadius = Math.max(cDims.depthFt, cDims.widthFt) / 2
        setbackEnd = Math.min(length * 0.35, colRadius + 0.04)
      } else {
        setbackEnd = Math.min(length * 0.25, 0.25)
      }
    } else {
      setbackStart = 0
      setbackEnd = 0
    }

    const trimmedLength = Math.max(0.1, length - (setbackStart + setbackEnd))
    if (m.type === 'beam' || m.type === 'joist') {
      depth = trimmedLength
    }

    if (m.type === 'column') {
      // Column's "depth" runs vertically (along the member), so what would
      // be depthFt/widthFt here are the two horizontal cross-section sides.
      width = depthFt
      height = Math.max(0.1, Math.abs(m.y2 - m.y1))
      depth = widthFt || depthFt
    }

    const wideFlange = (m.type === 'beam' || m.type === 'column') && this._isWideFlange(m.profile)

    let geom: THREE.BufferGeometry
    if (wideFlange && m.type === 'column') {
      // Column's length runs along local Y, not Z -- build the same I-shape
      // extruded along Z (the helper's convention) then rotate it upright.
      geom = this._iBeamGeometry(width, depth, height)
      geom.rotateX(-Math.PI / 2)
    } else if (wideFlange) {
      geom = this._iBeamGeometry(height, width, depth)
    } else {
      geom = new THREE.BoxGeometry(width, height, depth)
    }

    // Semi-matte shop-primed structural steel finish
    const mat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(colorHex),
      roughness: 0.55,
      metalness: 0.45,
      envMapIntensity: 0.6,
    })

    const mesh = new THREE.Mesh(geom, mat)

    if (m.type === 'column') {
      mesh.position.set(m.x1, (m.y1 + m.y2) / 2, m.z1)
    } else {
      const offsetDir = direction.clone().normalize()
      const center = startVec.clone().add(offsetDir.clone().multiplyScalar(setbackStart + trimmedLength / 2))
      mesh.position.copy(center)
      if (length > 0.001) {
        mesh.lookAt(endVec)
      }

      // Render 3D Shear Connection Plates / Tabs & 2 Bolts at both ends
      if (m.type === 'beam') {
        const plateHeight = Math.max(0.25, height * 0.65)
        const plateThick = 0.035 // ~3/8" plate
        const plateMat = new THREE.MeshStandardMaterial({
          color: new THREE.Color('#475569'), // structural steel connection plate
          roughness: 0.5,
          metalness: 0.6,
          envMapIntensity: 0.6,
        })
        const boltMat = new THREE.MeshStandardMaterial({
          color: new THREE.Color('#94A3B8'),
          roughness: 0.3,
          metalness: 0.8,
        })

        // Connection plate at Start joint
        const plateLenStart = setbackStart + 0.35
        const plateGeomStart = new THREE.BoxGeometry(plateThick, plateHeight, plateLenStart)
        const plateMeshStart = new THREE.Mesh(plateGeomStart, plateMat)
        plateMeshStart.position.set(0.02, 0, -trimmedLength / 2 + (plateLenStart / 2 - setbackStart))
        mesh.add(plateMeshStart)

        // 2 Bolts at Start joint
        const boltGeom = new THREE.CylinderGeometry(0.02, 0.02, plateThick * 1.6, 8)
        boltGeom.rotateZ(Math.PI / 2)
        const bolt1Start = new THREE.Mesh(boltGeom, boltMat)
        bolt1Start.position.set(0.01, plateHeight * 0.25, 0)
        plateMeshStart.add(bolt1Start)
        const bolt2Start = new THREE.Mesh(boltGeom, boltMat)
        bolt2Start.position.set(0.01, -plateHeight * 0.25, 0)
        plateMeshStart.add(bolt2Start)

        // Connection plate at End joint
        const plateLenEnd = setbackEnd + 0.35
        const plateGeomEnd = new THREE.BoxGeometry(plateThick, plateHeight, plateLenEnd)
        const plateMeshEnd = new THREE.Mesh(plateGeomEnd, plateMat)
        plateMeshEnd.position.set(0.02, 0, trimmedLength / 2 - (plateLenEnd / 2 - setbackEnd))
        mesh.add(plateMeshEnd)

        // 2 Bolts at End joint
        const bolt1End = new THREE.Mesh(boltGeom, boltMat)
        bolt1End.position.set(0.01, plateHeight * 0.25, 0)
        plateMeshEnd.add(bolt1End)
        const bolt2End = new THREE.Mesh(boltGeom, boltMat)
        bolt2End.position.set(0.01, -plateHeight * 0.25, 0)
        plateMeshEnd.add(bolt2End)
      }
    }

    return mesh
  }

  private _appendSceneMember(m: SceneMember) {
    const group = this._getOrCreateGroup(m.colorGroupKey)
    if (group.count >= group.capacity) this._growGroup(group)

    const idx = group.count
    this._writeSegment(group, idx, m.x1, m.y1, m.z1, m.x2, m.y2, m.z2)
    group.count++
    m.bufferIndex = idx
    this._flushGroup(group)

    // Create solid mesh
    const mesh = this._createSolidMesh(m, m.colorGroupKey)
    m.mesh = mesh
    this.scene?.add(mesh)

    this.members.set(m.globalId, m)
    for (const mid of m.memberIds) this.memberIdToGlobal.set(mid, m.globalId)
    this.spatialGrid.insert(m)
  }

  private _eraseSceneMember(m: SceneMember) {
    const group = this.colorGroups.get(m.colorGroupKey)
    if (!group) return

    // Swap with last segment
    const lastIdx = group.count - 1
    if (m.bufferIndex < lastIdx) {
      // Copy last → m's slot
      const srcBase = lastIdx * 6
      const dstBase = m.bufferIndex * 6
      for (let i = 0; i < 6; i++) group.positions[dstBase + i] = group.positions[srcBase + i]

      // Find the member that owned lastIdx and update its bufferIndex
      for (const sm of this.members.values()) {
        if (sm.colorGroupKey === m.colorGroupKey && sm.bufferIndex === lastIdx) {
          sm.bufferIndex = m.bufferIndex
          break
        }
      }
    }
    group.count--
    this._flushGroup(group)

    // Remove and dispose solid mesh and all child connection plates
    if (m.mesh) {
      this.scene?.remove(m.mesh)
      m.mesh.traverse((child) => {
        if (child instanceof THREE.Mesh) {
          child.geometry.dispose()
          if (Array.isArray(child.material)) {
            child.material.forEach(mat => mat.dispose())
          } else {
            child.material.dispose()
          }
        }
      })
      delete m.mesh
    }

    this.members.delete(m.globalId)
    for (const mid of m.memberIds) this.memberIdToGlobal.delete(mid)
    this.spatialGrid.removeFromCell(m)
  }

  // ── Deduplication ────────────────────────────────────────────────────────

  private _isDuplicate(x1: number, z1: number, x2: number, z2: number, type: string, floorId: string | null): SceneMember | null {
    const TOL = type === 'column' ? 1.5 : 1.0

    if (type === 'column') {
      // For columns: check proximity of the endpoint (columns are a point, x1=x2,z1=z2 semantically)
      const near = this.spatialGrid.findNear(x1, z1, TOL)
      for (const m of near) {
        if (m.type === 'column' && m.floorId === floorId) {
          const d = Math.hypot(m.x1 - x1, m.z1 - z1)
          if (d < TOL) return m
        }
      }
    } else {
      // For beams/braces: check both endpoint orderings.
      const near = this.spatialGrid.findNear(x1, z1, TOL)
      for (const m of near) {
        if (m.type !== type) continue
        if (m.floorId !== floorId) continue
        const d_ss = Math.hypot(m.x1 - x1, m.z1 - z1)
        const d_ee = Math.hypot(m.x2 - x2, m.z2 - z2)
        const d_se = Math.hypot(m.x1 - x2, m.z1 - z2)
        const d_es = Math.hypot(m.x2 - x1, m.z2 - z1)
        if ((d_ss < TOL && d_ee < TOL) || (d_se < TOL && d_es < TOL)) return m
      }
    }
    return null
  }

  // ── Public API ────────────────────────────────────────────────────────────

  /**
   * Incrementally add one page's worth of members to the scene.
   * Already-loaded pages are skipped unless force=true.
   */
  addPageMembers(pageId: string, rawMembers: RawMember[], force = false) {
    if (this.pageLoadedSet.has(pageId) && !force) return

    if (force) {
      // Remove existing members from this page before re-adding
      for (const m of [...this.members.values()]) {
        if (m.pageIds.includes(pageId)) {
          this._eraseSceneMember(m)
        }
      }
    }

    for (const raw of rawMembers) {
      const x1 = raw.start[0], y1 = raw.start[1], z1 = raw.start[2]
      const x2 = raw.end[0],   y2 = raw.end[1],   z2 = raw.end[2]
      const floorId = raw.floor_id || null

      const existing = this._isDuplicate(x1, z1, x2, z2, raw.type, floorId)
      if (existing) {
        // Merge into existing member
        existing.memberIds.push(raw.member_id)
        if (raw.merged_member_ids) existing.memberIds.push(...raw.merged_member_ids)
        if (!existing.pageIds.includes(pageId)) existing.pageIds.push(pageId)
        if (!existing.profile && raw.profile) existing.profile = raw.profile
        if (!existing.piecemark && raw.piecemark) existing.piecemark = raw.piecemark
        this.memberIdToGlobal.set(raw.member_id, existing.globalId)
        continue
      }

      const colorKey = getMemberColor(raw, this.colorMode, null)
      const sm: SceneMember = {
        globalId:      raw.id,
        memberIds:     [raw.member_id, ...(raw.merged_member_ids || [])],
        pageIds:       [pageId],
        x1, z1, x2, z2,
        y1, y2,
        elevation:     raw.start[1],
        type:          raw.type,
        profile:       raw.profile,
        piecemark:     raw.piecemark,
        unlabeled:     raw.unlabeled || false,
        floorId,
        floorName:     raw.floor_name || null,
        colorGroupKey: colorKey,
        bufferIndex:   -1,
        status:        raw.status ?? null,
        weight_lbs:    raw.weight_lbs ?? null,
        sequence:      raw.sequence ?? null,
        labor_code:    raw.labor_code ?? null,
        paint:         raw.paint ?? null,
      }
      this._appendSceneMember(sm)
    }

    this.pageLoadedSet.add(pageId)
    this.notify()
  }

  /**
   * Fully replace every column-type SceneMember with the latest set from a
   * merged-model fetch.
   */
  replaceColumns(rawColumns: RawMember[]) {
    for (const m of [...this.members.values()]) {
      if (m.type === 'column') this._eraseSceneMember(m)
    }

    for (const raw of rawColumns) {
      const x1 = raw.start[0], y1 = raw.start[1], z1 = raw.start[2]
      const x2 = raw.end[0],   y2 = raw.end[1],   z2 = raw.end[2]
      const colorKey = getMemberColor(raw, this.colorMode, null)
      const sm: SceneMember = {
        globalId:      raw.id,
        memberIds:     [raw.member_id, ...(raw.merged_member_ids || [])],
        pageIds:       [raw.page_id],
        x1, z1, x2, z2,
        y1, y2,
        elevation:     raw.start[1],
        type:          raw.type,
        profile:       raw.profile,
        piecemark:     raw.piecemark,
        unlabeled:     raw.unlabeled || false,
        floorId:       raw.floor_id || null,
        floorName:     raw.floor_name || null,
        colorGroupKey: colorKey,
        bufferIndex:   -1,
        status:        raw.status ?? null,
        weight_lbs:    raw.weight_lbs ?? null,
        sequence:      raw.sequence ?? null,
        labor_code:    raw.labor_code ?? null,
        paint:         raw.paint ?? null,
      }
      this._appendSceneMember(sm)
    }

    this.markDirty()
    this.notify()
  }

  /**
   * Add grid lines for a page (idempotent by grid id).
   */
  addPageGrids(rawGrids: RawGridLine[]) {
    let added = 0
    const seenLabels = new Set<string>()
    // Gather existing labels to avoid duplicate sprites
    this.gridGroup.children.forEach((c) => {
      if ((c as any).__gridLabel) seenLabels.add((c as any).__gridLabel)
    })

    const pts: number[] = []
    rawGrids.forEach((g) => {
      if (this.grids.has(g.id)) return
      this.grids.set(g.id, g)
      const gy1 = g.start[1] ?? 0
      const gy2 = g.end[1] ?? gy1
      pts.push(g.start[0], gy1, g.start[2], g.end[0], gy2, g.end[2])
      added++

      const labelKey = `${g.axis}:${g.label}`
      if (!seenLabels.has(labelKey)) {
        seenLabels.add(labelKey)
        const sprite = makeGridLabelSprite(g.label)
        sprite.position.set(g.start[0], gy1 + 0.5, g.start[2])
        ;(sprite as any).__gridLabel = labelKey
        this.gridGroup.add(sprite)
      }
    })

    if (pts.length === 0) return

    // Append new grid lines into a single LineSegments
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
    const mat = new THREE.LineBasicMaterial({ color: '#CBD5E1', transparent: true, opacity: 0.5 })
    this.gridGroup.add(new THREE.LineSegments(geo, mat))
    this.markDirty()
  }

  /**
   * Rebuild the entire scene from scratch (full replace, e.g. scope/colorMode change).
   */
  rebuildFull(allMembers: RawMember[], allGrids: RawGridLine[]) {
    // Clear all color groups (reuse THREE objects)
    for (const [, group] of this.colorGroups) {
      group.count = 0
      group.lineSegs.geometry.setDrawRange(0, 0)
    }
    // Dispose/remove existing solid meshes and connection hardware!
    for (const m of this.members.values()) {
      if (m.mesh) {
        this.scene?.remove(m.mesh)
        m.mesh.traverse((child) => {
          if (child instanceof THREE.Mesh) {
            child.geometry.dispose()
            if (Array.isArray(child.material)) {
              child.material.forEach(mat => mat.dispose())
            } else {
              child.material.dispose()
            }
          }
        })
      }
    }
    // Clear grid group
    while (this.gridGroup.children.length > 0) this.gridGroup.remove(this.gridGroup.children[0])

    this.members.clear()
    this.memberIdToGlobal.clear()
    this.grids.clear()
    this.spatialGrid.clear()
    this.pageLoadedSet.clear()

    // Re-populate: Always add all columns FIRST so all beams across all floors
    // can detect their column joints and attach shear connection tabs!
    const columns = allMembers.filter(m => m.type === 'column')
    const nonColumns = allMembers.filter(m => m.type !== 'column')

    this.replaceColumns(columns)

    const byPage = new Map<string, RawMember[]>()
    for (const m of nonColumns) {
      if (!byPage.has(m.page_id)) byPage.set(m.page_id, [])
      byPage.get(m.page_id)!.push(m)
    }
    for (const [pageId, mems] of byPage) {
      this.addPageMembers(pageId, mems, false)
    }
    this.addPageGrids(allGrids)

    this._fitCamera(allMembers, allGrids)
    this.notify()
  }

  /**
   * Fit camera to show all members.
   */
  _fitCamera(members: RawMember[], grids: RawGridLine[]) {
    if (!this.camera) return
    let minX = Infinity, maxX = -Infinity, minZ = Infinity, maxZ = -Infinity
    let minY = Infinity, maxY = -Infinity
    for (const m of members) {
      ;[m.start, m.end].forEach(([x, y, z]) => {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x)
        minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z)
        minY = Math.min(minY, y); maxY = Math.max(maxY, y)
      })
    }
    for (const g of grids) {
      ;[g.start, g.end].forEach(([x, , z]) => {
        minX = Math.min(minX, x); maxX = Math.max(maxX, x)
        minZ = Math.min(minZ, z); maxZ = Math.max(maxZ, z)
      })
    }
    if (!isFinite(minX)) { minX = 0; maxX = 100; minZ = 0; maxZ = 100 }
    if (!isFinite(minY)) { minY = 0; maxY = 0 }

    const cx = (minX + maxX) / 2, cz = (minZ + maxZ) / 2, cy = (minY + maxY) / 2
    const spanX = Math.max(maxX - minX, 10), spanZ = Math.max(maxZ - minZ, 10)
    const spanY = Math.max(maxY - minY, 0)

    const w = this.container?.clientWidth || 800
    const h = this.container?.clientHeight || 600
    const aspect = w / h
    // The framed span has to account for building height too, not just the
    // plan footprint -- otherwise a tall multi-floor building gets clipped
    // top/bottom once members actually render at their real elevation.
    let halfH = Math.max(spanZ, spanY) * 0.65
    let halfW = halfH * aspect
    if (halfW * 2 < spanX * 1.3) { halfW = spanX * 0.65; halfH = halfW / aspect }

    this.panX = cx; this.panY = cy; this.panZ = cz
    this.viewHalfW = halfW; this.viewHalfH = halfH
    this.zoom = 1.0
    this.orbitDistance = Math.max(halfW, halfH, spanY) * 2.5
    this.orbitAzimuth = CAMERA_PRESETS.home.azimuth
    this.orbitElevation = CAMERA_PRESETS.home.elevation
    this._applyCamera()
  }

  /** Camera position from orbit spherical coords around (panX, 0, panZ). */
  private _orbitPosition(): THREE.Vector3 {
    const r = this.orbitDistance / this.zoom
    const az = this.orbitAzimuth, el = this.orbitElevation
    return new THREE.Vector3(
      this.panX + r * Math.cos(el) * Math.sin(az),
      this.panY + r * Math.sin(el),
      this.panZ + r * Math.cos(el) * Math.cos(az),
    )
  }

  _applyCamera() {
    if (!this.orthoCam || !this.perspCam) return
    const target = new THREE.Vector3(this.panX, this.panY, this.panZ)
    const pos = this._orbitPosition()
    // Avoid the lookAt gimbal singularity that happens when the view
    // direction is (anti)parallel to the up vector (true top-down).
    const nearTop = this.orbitElevation > 85.0 * DEG
    const up = new THREE.Vector3(0, nearTop ? 0 : 1, nearTop ? -1 : 0)

    this.orthoCam.left   = -this.viewHalfW / this.zoom
    this.orthoCam.right  = this.viewHalfW / this.zoom
    this.orthoCam.top    = this.viewHalfH / this.zoom
    this.orthoCam.bottom = -this.viewHalfH / this.zoom
    this.orthoCam.up.copy(up)
    this.orthoCam.position.copy(pos)
    this.orthoCam.lookAt(target)
    this.orthoCam.updateProjectionMatrix()

    this.perspCam.up.copy(up)
    this.perspCam.position.copy(pos)
    this.perspCam.lookAt(target)
    this.perspCam.updateProjectionMatrix()

    this.camera = this.projectionMode === 'orthographic' ? this.orthoCam : this.perspCam
    this.markDirty()
  }

  // ── Camera controls (public API used by the toolbar / mouse handlers) ─────

  setProjectionMode(mode: ProjectionMode) {
    if (this.projectionMode === mode) return
    this.projectionMode = mode
    this._applyCamera()
    this.notify()
  }

  setCameraPreset(preset: CameraPreset) {
    const p = CAMERA_PRESETS[preset]
    this.orbitAzimuth = p.azimuth
    this.orbitElevation = p.elevation
    if (preset === 'home') this.zoom = 1.0
    this._applyCamera()
    this.notify()
  }

  /** Drag-to-orbit. Deltas are in pixels; sign/scale tuned for natural feel. */
  orbitBy(dxPixels: number, dyPixels: number) {
    const sensitivity = 0.005
    this.orbitAzimuth -= dxPixels * sensitivity
    const maxEl = 89 * DEG, minEl = -89 * DEG
    this.orbitElevation = Math.max(minEl, Math.min(maxEl, this.orbitElevation + dyPixels * sensitivity))
    this._applyCamera()
  }

  /** Drag-to-pan, camera-relative so it "just works" at any orbit angle. */
  panBy(dxPixels: number, dyPixels: number, viewportWidth: number, viewportHeight: number) {
    const worldPerPxX = (2 * this.viewHalfW / this.zoom) / viewportWidth
    const worldPerPxY = (2 * this.viewHalfH / this.zoom) / viewportHeight
    const az = this.orbitAzimuth
    // Screen-right and screen-up projected onto the ground (XZ) plane.
    const rightX = Math.cos(az), rightZ = -Math.sin(az)
    const fwdX = Math.sin(az), fwdZ = Math.cos(az)
    this.panX -= dxPixels * worldPerPxX * rightX - dyPixels * worldPerPxY * fwdX
    this.panZ -= dxPixels * worldPerPxX * rightZ - dyPixels * worldPerPxY * fwdZ
    this._applyCamera()
  }

  dolly(factor: number) {
    this.zoom = Math.max(0.1, Math.min(200, this.zoom * factor))
    this._applyCamera()
  }

  setGridVisible(visible: boolean) {
    this.gridGroup.visible = visible
    this.markDirty()
    this.notify()
  }

  /**
   * Change color mode — rebuilds all color group memberships in-place.
   */
  setColorMode(mode: ColorMode) {
    if (this.colorMode === mode) return
    this.colorMode = mode

    // Reset all group counts
    for (const [, g] of this.colorGroups) {
      g.count = 0
      g.lineSegs.geometry.setDrawRange(0, 0)
    }

    // Re-assign all members to new color groups
    for (const m of this.members.values()) {
      const newColor = getMemberColor(m, mode, this.selectedId)
      m.colorGroupKey = newColor
      if (m.mesh) {
        (m.mesh.material as THREE.MeshStandardMaterial).color.set(newColor)
      }
      const group = this._getOrCreateGroup(newColor)
      if (group.count >= group.capacity) this._growGroup(group)
      this._writeSegment(group, group.count, m.x1, m.y1, m.z1, m.x2, m.y2, m.z2)
      m.bufferIndex = group.count
      group.count++
    }

    for (const [, g] of this.colorGroups) this._flushGroup(g)
    // Colors just got reshuffled into (possibly new) groups -- re-apply any
    // legend hides so switching color-by mode doesn't silently un-hide
    // things the user had toggled off.
    for (const key of this.hiddenColorKeys) {
      const group = this.colorGroups.get(key)
      if (group) group.lineSegs.visible = false
    }
    this.notify()
  }

  // Legend chip toggle (e.g. click "Joists" to hide every joist). Cheap:
  // each color-group is already its own THREE.LineSegments object, so this
  // is just the standard Object3D.visible flag -- no buffer rewrite needed.
  // Also hides each member's SOLID mesh in that color group -- previously
  // this only hid the thin wireframe line, leaving the (now primary) solid
  // box still fully visible, so clicking a legend chip looked like it did
  // nothing.
  hiddenColorKeys = new Set<string>()
  setColorGroupVisible(colorKey: string, visible: boolean) {
    const group = this.colorGroups.get(colorKey)
    if (group) group.lineSegs.visible = visible
    if (visible) this.hiddenColorKeys.delete(colorKey)
    else this.hiddenColorKeys.add(colorKey)
    for (const m of this.members.values()) {
      if (m.colorGroupKey === colorKey && m.mesh && !this.hiddenTypes.has(m.type)) {
        m.mesh.visible = visible
      }
    }
    this.markDirty()
    this.notify()
  }

  // ── Type isolation (Layers panel) ─────────────────────────────────────────
  // Independent of color-by mode: "hide all columns" should work the same
  // whether you're currently coloring by Member Type, Status, or Weight.
  hiddenTypes = new Set<string>()
  setTypeVisible(kind: string, visible: boolean) {
    if (visible) this.hiddenTypes.delete(kind)
    else this.hiddenTypes.add(kind)
    for (const m of this.members.values()) {
      if (m.type !== kind || !m.mesh) continue
      // A member type is only actually visible if BOTH its type isn't
      // hidden AND its current color-group isn't separately hidden via the
      // legend -- the two hide mechanisms are independent and combine.
      m.mesh.visible = visible && !this.hiddenColorKeys.has(m.colorGroupKey)
    }
    this.markDirty()
    this.notify()
  }

  // ── Transparency / X-ray mode ───────────────────────────────────────────
  globalOpacity = 1
  setGlobalOpacity(value: number) {
    this.globalOpacity = Math.max(0.1, Math.min(1, value))
    for (const m of this.members.values()) {
      if (!m.mesh) continue
      const mat = m.mesh.material as THREE.MeshStandardMaterial
      mat.transparent = this.globalOpacity < 1
      mat.opacity = this.globalOpacity
      mat.depthWrite = this.globalOpacity >= 1
      mat.needsUpdate = true
    }
    this.markDirty()
    this.notify()
  }

  // ── Section / clipping plane ────────────────────────────────────────────
  // A single horizontal plane at world-Y `y` -- everything ABOVE it is
  // clipped away, so a user can "peel back" upper floors to inspect a
  // specific level's framing without switching scope and losing context of
  // the floors below it.
  clipPlane: THREE.Plane | null = null
  setClipY(y: number | null) {
    if (!this.renderer) return
    if (y === null) {
      this.clipPlane = null
      this.renderer.clippingPlanes = []
    } else {
      if (!this.clipPlane) this.clipPlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), y)
      else this.clipPlane.constant = y
      this.renderer.localClippingEnabled = true
      this.renderer.clippingPlanes = [this.clipPlane]
    }
    this.markDirty()
    this.notify()
  }

  // ── Fit camera to a subset or the whole building ───────────────────────
  fitToMembers(rawMemberIds: string[]) {
    if (!this.camera || rawMemberIds.length === 0) return
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity, minZ = Infinity, maxZ = -Infinity
    for (const rawId of rawMemberIds) {
      const gid = this.memberIdToGlobal.get(rawId)
      const m = gid ? this.members.get(gid) : null
      if (!m) continue
      minX = Math.min(minX, m.x1, m.x2); maxX = Math.max(maxX, m.x1, m.x2)
      minZ = Math.min(minZ, m.z1, m.z2); maxZ = Math.max(maxZ, m.z1, m.z2)
      minY = Math.min(minY, m.y1, m.y2); maxY = Math.max(maxY, m.y1, m.y2)
    }
    if (!isFinite(minX)) return
    const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2, cz = (minZ + maxZ) / 2
    const spanX = Math.max(maxX - minX, 4), spanY = Math.max(maxY - minY, 4), spanZ = Math.max(maxZ - minZ, 4)
    const w = this.container?.clientWidth || 800, h = this.container?.clientHeight || 600, aspect = w / h
    let halfH = Math.max(spanZ, spanY) * 0.9
    let halfW = halfH * aspect
    if (halfW * 2 < spanX * 1.3) { halfW = spanX * 0.9; halfH = halfW / aspect }
    this.panX = cx; this.panY = cy; this.panZ = cz
    this.viewHalfW = halfW; this.viewHalfH = halfH
    this.zoom = 1.0
    this.orbitDistance = Math.max(halfW, halfH, spanY) * 2.5
    this._applyCamera()
    this.notify()
  }

  fitToBuilding() {
    this.fitToMembers([...this.members.values()].map(m => m.memberIds[0]))
  }

  // ── Measurement tool ────────────────────────────────────────────────────
  // Click two points to get a real feet distance between them, matching the
  // structural-review "measure" workflow. Simplification: measures along
  // the ground plane (Y=0) using the same raycast screenToWorld() already
  // uses for picking -- snapping precisely to a clicked member's exact 3D
  // endpoint (including elevation) is a reasonable follow-up, not required
  // for a usable first version of the tool.
  measureMode = false
  measurePoints: THREE.Vector3[] = []
  private measureLine: THREE.Line | null = null
  toggleMeasureMode(on: boolean) {
    this.measureMode = on
    this.measurePoints = []
    this._clearMeasureLine()
    this.notify()
  }
  /** Returns the measured distance in feet once two points are placed, else null. */
  addMeasurePoint(worldX: number, worldZ: number): number | null {
    if (!this.measureMode) return null
    this.measurePoints.push(new THREE.Vector3(worldX, 0, worldZ))
    if (this.measurePoints.length === 2) {
      const [a, b] = this.measurePoints
      const dist = a.distanceTo(b)
      this._drawMeasureLine(a, b)
      this.measurePoints = []
      this.notify()
      return dist
    }
    this.notify()
    return null
  }
  private _clearMeasureLine() {
    if (this.measureLine) {
      this.scene?.remove(this.measureLine)
      this.measureLine.geometry.dispose()
      ;(this.measureLine.material as THREE.Material).dispose()
      this.measureLine = null
    }
    this.markDirty()
  }
  private _drawMeasureLine(a: THREE.Vector3, b: THREE.Vector3) {
    this._clearMeasureLine()
    const geo = new THREE.BufferGeometry().setFromPoints([a, b])
    const mat = new THREE.LineBasicMaterial({ color: '#F59E0B', linewidth: 2, depthTest: false })
    this.measureLine = new THREE.Line(geo, mat)
    this.scene?.add(this.measureLine)
    this.markDirty()
  }

  /**
   * Select a single member by raw member_id — thin wrapper around
   * applySelection() kept for the couple of call sites that only ever deal
   * with one id (e.g. member search).
   */
  selectMember(rawMemberId: string | null) {
    this.applySelection(rawMemberId ? new Set([rawMemberId]) : new Set())
  }

  /**
   * Highlight exactly the given set of raw member_ids in the 3D scene,
   * restoring everything else to its normal color — O(changed members),
   * not O(all members).
   *
   * This used to only ever take a single id (selectMember above), driven
   * off the workspace store's `selectedMemberId`. But the 2D plan canvas's
   * click handler calls setSelection()/toggleSelection() (which populate
   * the `selection` Set) rather than the workspace store's own
   * selectMember() action (which sets `selectedMemberId`) -- so clicking a
   * beam in the 2D plan updated `selection` (correct 2D highlight, correct
   * properties panel) but never touched `selectedMemberId`, and this
   * class's highlight logic was only ever wired to react to
   * `selectedMemberId`. Net effect: a 2D click never visibly highlighted
   * anything in 3D. Driving this off the full `selection` Set instead
   * fixes that for both single-click AND shift-click multi-select, in
   * both directions.
   */
  applySelection(rawMemberIds: Set<string>) {
    const prevIds = this.selectedIds
    const nextIds = new Set(rawMemberIds)

    // Restore members that are no longer selected
    for (const prevId of prevIds) {
      if (nextIds.has(prevId)) continue
      const globalId = this.memberIdToGlobal.get(prevId)
      if (!globalId) continue
      const m = this.members.get(globalId)
      if (!m) continue
      // Still selected via a different raw id merged into the same global
      // member (e.g. deduped across sheets) -- don't restore its color.
      if (m.memberIds.some(mid => nextIds.has(mid))) continue
      this._eraseSceneMember(m)
      m.colorGroupKey = getMemberColor(m, this.colorMode, null)
      this._appendSceneMember(m)
    }

    // Highlight newly selected members
    for (const nextId of nextIds) {
      if (prevIds.has(nextId)) continue
      const globalId = this.memberIdToGlobal.get(nextId)
      if (!globalId) continue
      const m = this.members.get(globalId)
      if (!m) continue
      this._eraseSceneMember(m)
      m.colorGroupKey = SELECTION_COLOR
      this._appendSceneMember(m)
    }

    this.selectedIds = nextIds
    this.selectedId = nextIds.size > 0 ? [...nextIds][0] : null

    this.markDirty()
    this.notify()
  }

  /**
   * Point-to-segment pick in plan XZ. Returns raw member_id of nearest member.
   */
  pickAt(worldX: number, worldZ: number, toleranceFt: number): string | null {
    let best: SceneMember | null = null
    let bestDist = toleranceFt
    const near = this.spatialGrid.findNear(worldX, worldZ, toleranceFt + 2)
    for (const m of near) {
      const dx = m.x2 - m.x1, dz = m.z2 - m.z1
      const lenSq = dx * dx + dz * dz
      let dist: number
      if (lenSq < 1e-10) {
        dist = Math.hypot(worldX - m.x1, worldZ - m.z1)
      } else {
        const t = Math.max(0, Math.min(1, ((worldX - m.x1) * dx + (worldZ - m.z1) * dz) / lenSq))
        dist = Math.hypot(worldX - (m.x1 + t * dx), worldZ - (m.z1 + t * dz))
      }
      if (dist < bestDist) { bestDist = dist; best = m }
    }
    return best ? best.memberIds[0] : null
  }

  /**
   * Screen point -> world XZ, via a real raycast against the Y=0 ground
   * plane. Works correctly regardless of orbit angle or projection type —
   * the old version assumed a fixed top-down orthographic camera and did
   * simple NDC math, which breaks as soon as the camera can tilt/rotate.
   */
  /**
   * Window/marquee selection — "Window selection: drag a rectangle to
   * select members fully inside it", matching the reference product's
   * tooltip verbatim. Projects both endpoints of every member to screen
   * space and requires BOTH inside the rect (not just intersecting it).
   */
  pickInRect(x0: number, y0: number, x1: number, y1: number, container: HTMLDivElement): string[] {
    if (!this.camera) return []
    const rect = container.getBoundingClientRect()
    const toScreen = (x: number, z: number): { sx: number; sy: number } | null => {
      const v = new THREE.Vector3(x, 0, z).project(this.camera!)
      if (v.z > 1) return null // behind camera
      return { sx: (v.x * 0.5 + 0.5) * rect.width, sy: (-v.y * 0.5 + 0.5) * rect.height }
    }
    const ids: string[] = []
    for (const m of this.members.values()) {
      const p1 = toScreen(m.x1, m.z1)
      const p2 = toScreen(m.x2, m.z2)
      if (!p1 || !p2) continue
      const inside = (p: { sx: number; sy: number }) => p.sx >= x0 && p.sx <= x1 && p.sy >= y0 && p.sy <= y1
      if (inside(p1) && inside(p2)) ids.push(m.memberIds[0])
    }
    return ids
  }

  screenToWorld(clientX: number, clientY: number, container: HTMLDivElement): { x: number; z: number } | null {
    if (!this.camera) return null
    const rect = container.getBoundingClientRect()
    const ndcX = ((clientX - rect.left) / rect.width) * 2 - 1
    const ndcY = -((clientY - rect.top) / rect.height) * 2 + 1
    this.raycaster.setFromCamera(new THREE.Vector2(ndcX, ndcY), this.camera)
    const hit = new THREE.Vector3()
    const ok = this.raycaster.ray.intersectPlane(this.groundPlane, hit)
    if (!ok) return null
    return { x: hit.x, z: hit.z }
  }

  handleResize(container: HTMLDivElement) {
    if (!this.renderer || !this.orthoCam || !this.perspCam) return
    const w = container.clientWidth, h = container.clientHeight
    this.renderer.setSize(w, h)
    const newAspect = w / h
    const halfH = this.viewHalfH / this.zoom
    this.orthoCam.left   = -halfH * newAspect
    this.orthoCam.right  = halfH * newAspect
    this.orthoCam.top    = halfH
    this.orthoCam.bottom = -halfH
    this.orthoCam.updateProjectionMatrix()
    this.perspCam.aspect = newAspect
    this.perspCam.updateProjectionMatrix()
    this.markDirty()
  }
}

// Module-level singleton — survives React re-renders
export const buildingScene = new BuildingSceneStore()

// TEMP DEBUG: expose for runtime inspection via browser console/devtools.
// Safe to leave -- read-only diagnostic surface, not used by any app code.
if (typeof window !== 'undefined') {
  ;(window as any).__buildingScene = buildingScene
  ;(window as any).__THREE = THREE
}

// ─── Grid label sprite (moved here from StructuralViewer3D) ──────────────────

export function makeGridLabelSprite(label: string): THREE.Sprite {
  const canvas = document.createElement('canvas')
  canvas.width = 64; canvas.height = 64
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = 'rgba(255,255,255,0.85)'
  ctx.beginPath()
  ctx.arc(32, 32, 28, 0, Math.PI * 2)
  ctx.fill()
  ctx.strokeStyle = '#94A3B8'
  ctx.lineWidth = 2
  ctx.stroke()
  ctx.fillStyle = '#334155'
  ctx.font = 'bold 22px sans-serif'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(label.slice(0, 3), 32, 32)
  const tex = new THREE.CanvasTexture(canvas)
  const mat = new THREE.SpriteMaterial({ map: tex, depthTest: false })
  const sprite = new THREE.Sprite(mat)
  sprite.scale.set(4, 4, 1)
  return sprite
}
