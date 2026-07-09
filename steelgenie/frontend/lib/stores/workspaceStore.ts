import { create } from 'zustand'

export type ToolType = 'select' | 'hand' | 'ruler' | 'marker' | 'column' | 'beam' | 'brace'

export interface Point {
  x: number
  y: number
}

export interface CropRect {
  x0: number
  y0: number
  x1: number
  y1: number
}

export interface RulerLine {
  x1: number
  y1: number
  x2: number
  y2: number
}

export interface LayerPreset {
  id: string
  name: string
  classVisibility: Record<string, boolean>
  classOpacity: Record<string, number>
  classColors: Record<string, string>
  aids: {
    markers: boolean
    rulers: boolean
    labels: boolean
    confidenceHalo: boolean
    detectionRegion: boolean
    grid: boolean
    piecemarks: boolean
    lengths: boolean
    reactions: boolean
    columnProjections: boolean
    lengthFilter: boolean
  }
  colorMode: 'kind' | 'status' | 'confidence' | 'section'
}

export interface LayersState {
  classVisibility: Record<string, boolean>
  classOpacity: Record<string, number>
  classColors: Record<string, string>
  planVisible: boolean
  aids: {
    markers: boolean
    rulers: boolean
    labels: boolean
    confidenceHalo: boolean
    detectionRegion: boolean
    grid: boolean
    piecemarks: boolean
    lengths: boolean
    reactions: boolean
    columnProjections: boolean
    lengthFilter: boolean
  }
  colorMode: 'kind' | 'status' | 'confidence' | 'section'
  activePresetId: string | null
  hiddenLegendKeys: Set<string>
}

export const DEFAULT_PRESETS: LayerPreset[] = [
  {
    id: 'preset-all',
    name: 'All',
    classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
    classOpacity: { beam: 1, column: 1, vbrace: 1, hbrace: 1, joist: 1, unlabelled: 1 },
    classColors: { column: '#3B82F6', beam: '#EC4899', vbrace: '#F59E0B', hbrace: '#06B6D4', joist: '#8B5CF6', unlabelled: '#64748B' },
    aids: {
      markers: true,
      rulers: true,
      labels: true,
      confidenceHalo: true,
      detectionRegion: true,
      grid: true,
      piecemarks: true,
      lengths: false,
      reactions: false,
      columnProjections: true,
      lengthFilter: false,
    },
    colorMode: 'kind'
  },
  {
    id: 'preset-steel',
    name: 'Steel only',
    classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
    classOpacity: { beam: 1, column: 1, vbrace: 1, hbrace: 1, joist: 1, unlabelled: 1 },
    classColors: { column: '#3B82F6', beam: '#EC4899', vbrace: '#F59E0B', hbrace: '#06B6D4', joist: '#8B5CF6', unlabelled: '#64748B' },
    aids: {
      markers: false,
      rulers: false,
      labels: false,
      confidenceHalo: false,
      detectionRegion: false,
      grid: false,
      piecemarks: false,
      lengths: false,
      reactions: false,
      columnProjections: false,
      lengthFilter: false,
    },
    colorMode: 'kind'
  },
  {
    id: 'preset-qa',
    name: 'QA pass',
    classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
    classOpacity: { beam: 1, column: 1, vbrace: 1, hbrace: 1, joist: 1, unlabelled: 1 },
    classColors: { column: '#3B82F6', beam: '#EC4899', vbrace: '#F59E0B', hbrace: '#06B6D4', joist: '#8B5CF6', unlabelled: '#64748B' },
    aids: {
      markers: true,
      rulers: true,
      labels: true,
      confidenceHalo: true,
      detectionRegion: false,
      grid: true,
      piecemarks: true,
      lengths: false,
      reactions: false,
      columnProjections: true,
      lengthFilter: false,
    },
    colorMode: 'confidence'
  },
  {
    id: 'preset-braces',
    name: 'Braces check',
    classVisibility: { beam: false, column: false, vbrace: true, hbrace: true, joist: false, unlabelled: false },
    classOpacity: { beam: 1, column: 1, vbrace: 1, hbrace: 1, joist: 1, unlabelled: 1 },
    classColors: { column: '#3B82F6', beam: '#EC4899', vbrace: '#F59E0B', hbrace: '#06B6D4', joist: '#8B5CF6', unlabelled: '#64748B' },
    aids: {
      markers: true,
      rulers: true,
      labels: true,
      confidenceHalo: false,
      detectionRegion: false,
      grid: true,
      piecemarks: true,
      lengths: false,
      reactions: false,
      columnProjections: true,
      lengthFilter: false,
    },
    colorMode: 'kind'
  }
]

const getInitialLayers = (): LayersState => {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem('calsteel-layers')
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        parsed.hiddenLegendKeys = new Set(parsed.hiddenLegendKeys || [])
        // Fill back-compatibility keys if missing
        if (parsed.planVisible === undefined) parsed.planVisible = true
        if (!parsed.aids) parsed.aids = {}
        if (parsed.aids.piecemarks === undefined) parsed.aids.piecemarks = true
        if (parsed.aids.lengths === undefined) parsed.aids.lengths = false
        if (parsed.aids.reactions === undefined) parsed.aids.reactions = false
        if (parsed.aids.columnProjections === undefined) parsed.aids.columnProjections = true
        if (parsed.aids.lengthFilter === undefined) parsed.aids.lengthFilter = false
        return parsed
      } catch {
        // ignore
      }
    }
  }
  return {
    classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
    classOpacity: { beam: 1.0, column: 1.0, vbrace: 1.0, hbrace: 1.0, joist: 1.0, unlabelled: 1.0 },
    classColors: { column: '#3B82F6', beam: '#EC4899', vbrace: '#F59E0B', hbrace: '#06B6D4', joist: '#8B5CF6', unlabelled: '#64748B' },
    planVisible: true,
    aids: {
      markers: true,
      rulers: true,
      labels: true,
      confidenceHalo: false,
      detectionRegion: false,
      grid: false,
      piecemarks: true,
      lengths: false,
      reactions: false,
      columnProjections: true,
      lengthFilter: false,
    },
    colorMode: 'kind',
    activePresetId: null,
    hiddenLegendKeys: new Set<string>()
  }
}

const getInitialPresets = (): LayerPreset[] => {
  if (typeof window !== 'undefined') {
    const saved = localStorage.getItem('calsteel-presets')
    if (saved) {
      try {
        const parsed = JSON.parse(saved)
        // ensure default aids are populated
        const validated = parsed.map((p: any) => ({
          ...p,
          aids: {
            markers: true,
            rulers: true,
            labels: true,
            confidenceHalo: false,
            detectionRegion: false,
            grid: false,
            piecemarks: true,
            lengths: false,
            reactions: false,
            columnProjections: true,
            lengthFilter: false,
            ...p.aids
          }
        }))
        return [...DEFAULT_PRESETS, ...validated]
      } catch {
        // ignore
      }
    }
  }
  return DEFAULT_PRESETS
}

interface WorkspaceState {
  activeTool: ToolType
  zoomLevel: number
  isPanning: boolean
  cropMode: boolean
  cropDrag: CropRect | null
  cropRect: CropRect | null
  rulerStart: Point | null
  rulerEnd: Point | null
  rulerDragging: boolean
  markerDots: Point[]
  rulerLines: RulerLine[]
  undoStack: ('marker' | 'ruler')[]
  selectedMemberId: string | null
  activeTab: 'Plans' | 'BOM'
  currentPageId: string | null
  currentPageIndex: number
  selectedRatio: number | null
  selectedScale: string | null
  wrapperSize: { w: number; h: number }
  imageNaturalWidth: number | null
  imageAspect: number

  // Member Segregation state
  selection: Set<string>
  hiddenIds: Set<string>
  isolation: { kind?: string; ids?: Set<string> } | null
  searchQuery: string
  zoomTarget: { id: string; nonce: number } | null

  // Layer Redesign slice
  layers: LayersState
  presets: LayerPreset[]

  setTool: (tool: ToolType) => void
  setZoom: (zoom: number) => void
  setIsPanning: (panning: boolean) => void
  setCropMode: (mode: boolean) => void
  setCropDrag: (drag: CropRect | null) => void
  setCropRect: (rect: CropRect | null) => void
  setRulerStart: (pt: Point | null) => void
  setRulerEnd: (pt: Point | null) => void
  setRulerDragging: (dragging: boolean) => void
  addMarkerDot: (pt: Point) => void
  addRulerLine: (line: RulerLine) => void
  pushUndo: (type: 'marker' | 'ruler') => void
  popUndo: () => void
  selectMember: (id: string | null) => void
  setActiveTab: (tab: 'Plans' | 'BOM') => void
  setCurrentPage: (id: string | null, idx: number) => void
  setScale: (label: string | null, ratio: number | null) => void
  setWrapperSize: (w: number, h: number) => void
  setImageNaturalWidth: (w: number | null) => void
  setImageAspect: (a: number) => void
  resetTakeoffState: () => void

  // Member Segregation mutations
  setSelection: (ids: Set<string>) => void
  toggleSelection: (id: string) => void
  clearSelection: () => void
  toggleMemberVisibility: (id: string, visible?: boolean) => void
  showAllMembers: () => void
  setIsolation: (isolation: { kind?: string; ids?: Set<string> } | null) => void
  setSearchQuery: (q: string) => void
  setZoomTarget: (id: string | null) => void

  // Layer slice mutations
  toggleLayerVisibility: (kind: string) => void
  togglePlanVisibility: () => void
  setLayerOpacity: (kind: string, opacity: number) => void
  setLayerColor: (kind: string, hexColor: string) => void
  toggleAid: (aidName: string) => void
  setColorMode: (mode: 'kind' | 'status' | 'confidence' | 'section') => void
  applyPreset: (presetId: string) => void
  savePreset: (name: string) => void
  deletePreset: (id: string) => void
  setPresetsFromServer: (serverPresets: LayerPreset[]) => void
  toggleLegendKey: (key: string) => void
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  activeTool: 'select',
  zoomLevel: 1.0,
  isPanning: false,
  cropMode: false,
  cropDrag: null,
  cropRect: null,
  rulerStart: null,
  rulerEnd: null,
  rulerDragging: false,
  markerDots: [],
  rulerLines: [],
  undoStack: [],
  selectedMemberId: null,
  activeTab: 'Plans',
  currentPageId: null,
  currentPageIndex: 0,
  selectedRatio: null,
  selectedScale: null,
  wrapperSize: { w: 1, h: 1 },
  imageNaturalWidth: null,
  imageAspect: 0.75,

  // State defaults
  selection: new Set<string>(),
  hiddenIds: new Set<string>(),
  isolation: null,
  searchQuery: '',
  zoomTarget: null,

  layers: getInitialLayers(),
  presets: getInitialPresets(),

  setTool: (tool) => set({ activeTool: tool }),
  setZoom: (zoom) => set({ zoomLevel: zoom }),
  setIsPanning: (panning) => set({ isPanning: panning }),
  setCropMode: (mode) => set({ cropMode: mode }),
  setCropDrag: (drag) => set({ cropDrag: drag }),
  setCropRect: (rect) => set({ cropRect: rect }),
  setRulerStart: (pt) => set({ rulerStart: pt }),
  setRulerEnd: (pt) => set({ rulerEnd: pt }),
  setRulerDragging: (dragging) => set({ rulerDragging: dragging }),
  addMarkerDot: (pt) => set((state) => ({ markerDots: [...state.markerDots, pt] })),
  addRulerLine: (line) => set((state) => ({ rulerLines: [...state.rulerLines, line] })),
  pushUndo: (type) => set((state) => ({ undoStack: [...state.undoStack, type] })),
  popUndo: () =>
    set((state) => {
      const nextStack = [...state.undoStack]
      const last = nextStack.pop()
      if (!last) return {}

      if (last === 'marker') {
        const nextMarkers = [...state.markerDots]
        nextMarkers.pop()
        return { undoStack: nextStack, markerDots: nextMarkers }
      } else {
        const nextLines = [...state.rulerLines]
        nextLines.pop()
        return { undoStack: nextStack, rulerLines: nextLines }
      }
    }),
  selectMember: (id) => set({ selectedMemberId: id, selection: id ? new Set([id]) : new Set() }),
  setActiveTab: (tab) => set({ activeTab: tab }),
  setCurrentPage: (id, idx) => set({ currentPageId: id, currentPageIndex: idx }),
  setScale: (label, ratio) => set({ selectedScale: label, selectedRatio: ratio }),
  setWrapperSize: (w, h) => set({ wrapperSize: { w, h } }),
  setImageNaturalWidth: (w) => set({ imageNaturalWidth: w }),
  setImageAspect: (a) => set({ imageAspect: a }),
  resetTakeoffState: () =>
    set((state) => {
      const defaultLayers = {
        classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
        classOpacity: { beam: 1.0, column: 1.0, vbrace: 1.0, hbrace: 1.0, joist: 1.0, unlabelled: 1.0 },
        classColors: { column: '#3B82F6', beam: '#EC4899', vbrace: '#F59E0B', hbrace: '#06B6D4', joist: '#8B5CF6', unlabelled: '#64748B' },
        planVisible: true,
        aids: {
          markers: true,
          rulers: true,
          labels: true,
          confidenceHalo: false,
          detectionRegion: false,
          grid: false,
          piecemarks: true,
          lengths: false,
          reactions: false,
          columnProjections: true,
          lengthFilter: false,
        },
        colorMode: 'kind' as const,
        activePresetId: null,
        hiddenLegendKeys: new Set<string>()
      }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...defaultLayers, hiddenLegendKeys: [] }))
      return {
        activeTool: 'select',
        zoomLevel: 1.0,
        isPanning: false,
        cropMode: false,
        cropDrag: null,
        cropRect: null,
        rulerStart: null,
        rulerEnd: null,
        rulerDragging: false,
        markerDots: [],
        rulerLines: [],
        undoStack: [],
        selectedMemberId: null,
        selection: new Set(),
        hiddenIds: new Set(),
        isolation: null,
        zoomTarget: null,
        layers: defaultLayers
      }
    }),

  // Mutations
  setSelection: (ids) => set({ selection: ids }),
  toggleSelection: (id) =>
    set((state) => {
      const next = new Set(state.selection)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      const singleId = next.size === 1 ? Array.from(next)[0] : null
      return { selection: next, selectedMemberId: singleId }
    }),
  clearSelection: () => set({ selection: new Set(), selectedMemberId: null }),
  toggleMemberVisibility: (id, visible) =>
    set((state) => {
      const next = new Set(state.hiddenIds)
      const shouldHide = visible !== undefined ? !visible : !next.has(id)
      if (shouldHide) {
        next.add(id)
      } else {
        next.delete(id)
      }
      return { hiddenIds: next }
    }),
  showAllMembers: () =>
    set((state) => {
      const nextLayers = {
        ...state.layers,
        classVisibility: { beam: true, column: true, vbrace: true, hbrace: true, joist: true, unlabelled: true },
        hiddenLegendKeys: new Set<string>()
      }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: [] }))
      return { hiddenIds: new Set(), layers: nextLayers }
    }),
  setIsolation: (iso) => set({ isolation: iso }),
  setSearchQuery: (q) => set({ searchQuery: q }),
  setZoomTarget: (id) =>
    set((state) => ({
      zoomTarget: id ? { id, nonce: (state.zoomTarget?.nonce ?? 0) + 1 } : null,
    })),

  // Layer slice mutations
  toggleLayerVisibility: (kind) =>
    set((state) => {
      const nextVis = { ...state.layers.classVisibility, [kind]: !state.layers.classVisibility[kind] }
      const nextLayers = { ...state.layers, classVisibility: nextVis, activePresetId: null }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  togglePlanVisibility: () =>
    set((state) => {
      const nextLayers = { ...state.layers, planVisible: !state.layers.planVisible }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  setLayerOpacity: (kind, opacity) =>
    set((state) => {
      const nextOp = { ...state.layers.classOpacity, [kind]: opacity }
      const nextLayers = { ...state.layers, classOpacity: nextOp, activePresetId: null }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  setLayerColor: (kind, hexColor) =>
    set((state) => {
      const nextColors = { ...state.layers.classColors, [kind]: hexColor }
      const nextLayers = { ...state.layers, classColors: nextColors }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  toggleAid: (aidName) =>
    set((state) => {
      const nextAids = { ...state.layers.aids, [aidName as keyof typeof state.layers.aids]: !state.layers.aids[aidName as keyof typeof state.layers.aids] }
      const nextLayers = { ...state.layers, aids: nextAids, activePresetId: null }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  setColorMode: (mode) =>
    set((state) => {
      const nextLayers = { ...state.layers, colorMode: mode, activePresetId: null }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(nextLayers.hiddenLegendKeys) }))
      return { layers: nextLayers }
    }),
  applyPreset: (presetId) =>
    set((state) => {
      const preset = state.presets.find((p) => p.id === presetId)
      if (!preset) return {}
      const nextLayers = {
        classVisibility: { ...preset.classVisibility },
        classOpacity: { ...preset.classOpacity },
        classColors: { ...preset.classColors },
        planVisible: true,
        aids: { ...preset.aids },
        colorMode: preset.colorMode,
        activePresetId: presetId,
        hiddenLegendKeys: new Set<string>()
      }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: [] }))
      return { layers: nextLayers }
    }),
  savePreset: (name) =>
    set((state) => {
      const newPreset: LayerPreset = {
        id: 'preset-' + Date.now(),
        name,
        classVisibility: { ...state.layers.classVisibility },
        classOpacity: { ...state.layers.classOpacity },
        classColors: { ...state.layers.classColors },
        aids: { ...state.layers.aids },
        colorMode: state.layers.colorMode,
      }
      const userPresetsOnly = state.presets.filter((p) => !DEFAULT_PRESETS.find((d) => d.id === p.id))
      const nextUserPresets = [...userPresetsOnly, newPreset]
      localStorage.setItem('calsteel-presets', JSON.stringify(nextUserPresets))

      const nextPresets = [...state.presets, newPreset]
      return { presets: nextPresets, layers: { ...state.layers, activePresetId: newPreset.id } }
    }),
  deletePreset: (id) =>
    set((state) => {
      if (DEFAULT_PRESETS.find((d) => d.id === id)) return {}
      const nextPresets = state.presets.filter((p) => p.id !== id)
      const userPresetsOnly = nextPresets.filter((p) => !DEFAULT_PRESETS.find((d) => d.id === p.id))
      localStorage.setItem('calsteel-presets', JSON.stringify(userPresetsOnly))
      return {
        presets: nextPresets,
        layers: {
          ...state.layers,
          activePresetId: state.layers.activePresetId === id ? null : state.layers.activePresetId,
        },
      }
    }),
  setPresetsFromServer: (serverPresets) =>
    set((state) => {
      const userPresets = serverPresets.filter((sp) => !DEFAULT_PRESETS.find((d) => d.id === sp.id))
      return { presets: [...DEFAULT_PRESETS, ...userPresets] }
    }),
  toggleLegendKey: (key) =>
    set((state) => {
      const next = new Set(state.layers.hiddenLegendKeys)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      const nextLayers = { ...state.layers, hiddenLegendKeys: next }
      localStorage.setItem('calsteel-layers', JSON.stringify({ ...nextLayers, hiddenLegendKeys: Array.from(next) }))
      return { layers: nextLayers }
    }),
}))

export const getMemberRenderProps = (
  state: { layers: LayersState; hiddenIds: Set<string>; isolation: { kind?: string; ids?: Set<string> } | null },
  member: { id: string; kind: string; confidence?: number | null; status?: string; section?: string | null }
) => {
  const { layers, hiddenIds, isolation } = state
  const mKind = member.kind

  // 1. Central Legend toggle checks
  if (layers.hiddenLegendKeys && layers.hiddenLegendKeys.size > 0) {
    if (layers.colorMode === 'status' && member.status && layers.hiddenLegendKeys.has(member.status)) {
      return { visible: false, color: '#64748B', opacity: 0 }
    }
    if (layers.colorMode === 'section' && member.section && layers.hiddenLegendKeys.has(member.section)) {
      return { visible: false, color: '#64748B', opacity: 0 }
    }
    if (layers.colorMode === 'confidence') {
      const conf = member.confidence ?? 0
      let tier = '<50%'
      if (conf >= 0.9) tier = '>90%'
      else if (conf >= 0.7) tier = '>70%'
      else if (conf >= 0.5) tier = '>50%'
      if (layers.hiddenLegendKeys.has(tier)) {
        return { visible: false, color: '#64748B', opacity: 0 }
      }
    }
  }

  // 2. Determine visibility
  let visible = true

  // Check if member is hidden by ID
  if (hiddenIds.has(member.id)) {
    visible = false
  }

  // Check if member class is visible
  let classKey = mKind
  if (mKind === 'brace') classKey = 'vbrace'
  if (mKind === 'vbrace') classKey = 'vbrace'
  if (mKind === 'hbrace') classKey = 'hbrace'

  if (layers.classVisibility[classKey] === false) {
    visible = false
  }

  // Handle isolation (solo category or IDs)
  if (isolation) {
    if (isolation.kind) {
      const isMatch =
        mKind === isolation.kind ||
        (isolation.kind === 'vbrace' && (mKind === 'vbrace' || mKind === 'hbrace' || mKind === 'brace'))
      if (!isMatch) {
        visible = false
      }
    } else if (isolation.ids && !isolation.ids.has(member.id)) {
      visible = false
    }
  }

  // 3. Determine color
  let color = layers.classColors[classKey] || '#10B981'

  // If isolation is active for a category and matches, it should be colored green
  if (isolation && isolation.kind) {
    const isMatch =
      mKind === isolation.kind ||
      (isolation.kind === 'vbrace' && (mKind === 'vbrace' || mKind === 'hbrace' || mKind === 'brace'))
    if (isMatch) {
      color = '#10B981' // Green
    }
  } else {
    // If not isolated, respect colorMode
    if (layers.colorMode === 'status') {
      if (member.status === 'verified') color = '#10B981'
      else if (member.status === 'rejected') color = '#EF4444'
      else if (member.status === 'need_review') color = '#F59E0B'
      else color = '#64748B'
    } else if (layers.colorMode === 'confidence') {
      const conf = member.confidence ?? 0
      if (conf >= 0.9) color = '#10B981'
      else if (conf >= 0.7) color = '#3B82F6'
      else if (conf >= 0.5) color = '#F59E0B'
      else color = '#EF4444'
    } else if (layers.colorMode === 'section') {
      const section = member.section || 'Unspecified'
      let hash = 0
      for (let i = 0; i < section.length; i++) {
        hash = section.charCodeAt(i) + ((hash << 5) - hash)
      }
      const colors = [
        '#3B82F6',
        '#EF4444',
        '#10B981',
        '#F59E0B',
        '#8B5CF6',
        '#EC4899',
        '#06B6D4',
        '#14B8A6',
      ]
      color = colors[Math.abs(hash) % colors.length]
    }
  }

  // 4. Determine opacity
  let opacity = layers.classOpacity[classKey] ?? 1.0
  if (isolation && !isolation.kind && isolation.ids && !isolation.ids.has(member.id)) {
    // Dimmed state for specific selection isolation
    opacity = 0.15
    visible = true
  }

  return { visible, color, opacity }
}
