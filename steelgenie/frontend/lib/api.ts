import { supabase } from './supabase'

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000'

async function getAuthToken() {
  const {
    data: { session },
  } = await supabase.auth.getSession()
  let token = session?.access_token
  if (!token && typeof window !== 'undefined') {
    try {
      const mockStr = localStorage.getItem('dev_auth_session')
      if (mockStr) {
        const parsed = JSON.parse(mockStr)
        token = parsed.access_token
      }
    } catch {
      // ignore
    }
  }
  return token
}

/**
 * Authenticated fetch wrapper.
 * Injects the Supabase session JWT into every request.
 */
export async function apiFetch(path: string, init: RequestInit = {}) {
  const token = await getAuthToken()

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...init.headers,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })

  if (!res.ok) {
    const text = await res.text()
    let msg = text
    try {
      const parsed = JSON.parse(text)
      if (parsed.detail) {
        msg = typeof parsed.detail === 'string' ? parsed.detail : JSON.stringify(parsed.detail)
      }
    } catch {
      // use text fallback
    }
    throw new Error(msg || `HTTP ${res.status}`)
  }

  // Handle 204 No Content
  if (res.status === 204) {
    return null
  }

  return res.json()
}

/**
 * Upload a PDF file to a project.
 */
export async function uploadDrawing(projectId: string, file: File) {
  const token = await getAuthToken()

  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${BASE}/api/v1/projects/${projectId}/drawings`, {
    method: 'POST',
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: formData,
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(text || `HTTP ${res.status}`)
  }

  return res.json()
}

// ── PROJECT API ─────────────────────────────────────────────────────────────
export const projectsApi = {
  list: () => apiFetch('/api/v1/projects'),
  get: (id: string) => apiFetch(`/api/v1/projects/${id}`),
  create: (data: any) =>
    apiFetch('/api/v1/projects', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: string, data: any) =>
    apiFetch(`/api/v1/projects/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  delete: (id: string) =>
    apiFetch(`/api/v1/projects/${id}`, {
      method: 'DELETE',
    }),
  pin: (id: string) =>
    apiFetch(`/api/v1/projects/${id}/pin`, {
      method: 'POST',
    }),
  clone: (id: string) =>
    apiFetch(`/api/v1/projects/${id}/clone`, {
      method: 'POST',
    }),
}

// ── DRAWINGS & PAGES API ─────────────────────────────────────────────────────
export const drawingsApi = {
  list: (projectId: string) => apiFetch(`/api/v1/projects/${projectId}/drawings`),
  listPages: (drawingId: string) => apiFetch(`/api/v1/drawings/${drawingId}/pages`),
  getPage: (pageId: string) => apiFetch(`/api/v1/pages/${pageId}`),
  updatePage: (pageId: string, data: any) =>
    apiFetch(`/api/v1/pages/${pageId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
}

// ── MEMBERS API ──────────────────────────────────────────────────────────────
export const membersApi = {
  list: (pageId: string) => apiFetch(`/api/v1/pages/${pageId}/members`),
  create: (pageId: string, data: any) =>
    apiFetch(`/api/v1/pages/${pageId}/members`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: string, data: any) =>
    apiFetch(`/api/v1/members/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  delete: (id: string) =>
    apiFetch(`/api/v1/members/${id}`, {
      method: 'DELETE',
    }),
  bulkUpdate: (ids: string[], update: any) =>
    apiFetch('/api/v1/members/bulk-update', {
      method: 'POST',
      body: JSON.stringify({ ids, update }),
    }),
  bulkDelete: (ids: string[]) =>
    apiFetch('/api/v1/members/bulk-delete', {
      method: 'POST',
      body: JSON.stringify({ ids }),
    }),
  analyse: (pageId: string, options: any) =>
    apiFetch(`/api/v1/pages/${pageId}/analyse`, {
      method: 'POST',
      body: JSON.stringify(options),
    }),
}

// ── BOM API ──────────────────────────────────────────────────────────────────
export const bomApi = {
  list: (projectId: string, params: Record<string, any> = {}) => {
    const qs = new URLSearchParams(params).toString()
    return apiFetch(`/api/v1/projects/${projectId}/bom${qs ? '?' + qs : ''}`)
  },
  summary: (projectId: string) => apiFetch(`/api/v1/projects/${projectId}/bom/summary`),
  generate: (projectId: string) =>
    apiFetch(`/api/v1/projects/${projectId}/bom/generate`, {
      method: 'POST',
    }),
  getExportUrl: (projectId: string) => `${BASE}/api/v1/projects/${projectId}/bom/export/csv`,
  getKissExportUrl: (projectId: string) => `${BASE}/api/v1/exports/projects/${projectId}/kiss`,
  getEpmExportUrl: (projectId: string) => `${BASE}/api/v1/exports/projects/${projectId}/epm`,
}

// ── JOBS API ─────────────────────────────────────────────────────────────────
export const jobsApi = {
  get: (jobId: string) => apiFetch(`/api/v1/jobs/${jobId}`),
}

// ── MODEL API ────────────────────────────────────────────────────────────────
export const modelApi = {
  get: (projectId: string, pageId: string, ratio = 96, elev = 12) =>
    apiFetch(
      `/api/v1/projects/${projectId}/model?page_id=${pageId}&scale_ratio=${ratio}&floor_elevation_ft=${elev}`
    ),
}

// ── CONFIG API ───────────────────────────────────────────────────────────────
export const configApi = {
  get: (projectId: string) => apiFetch(`/api/v1/projects/${projectId}/configuration`),
  update: (projectId: string, payload: any) =>
    apiFetch(`/api/v1/projects/${projectId}/configuration`, {
      method: 'PUT',
      body: JSON.stringify({ payload }),
    }),
}

// ── NOTIFICATIONS API ────────────────────────────────────────────────────────
export const notificationsApi = {
  list: () => apiFetch('/api/v1/notifications'),
  read: (id: string) => apiFetch(`/api/v1/notifications/${id}/read`, { method: 'POST' }),
  readAll: () => apiFetch('/api/v1/notifications/read-all', { method: 'POST' }),
}

// ── SECTIONS API ─────────────────────────────────────────────────────────────
export const sectionsApi = {
  search: (q?: string, standard?: string, sectionType?: string) => {
    const params = new URLSearchParams()
    if (q) params.append('q', q)
    if (standard) params.append('standard', standard)
    if (sectionType) params.append('section_type', sectionType)
    const qs = params.toString()
    return apiFetch(`/api/v1/sections${qs ? '?' + qs : ''}`)
  },
  get: (designation: string) => apiFetch(`/api/v1/sections/${designation}`),
}

// ── LAYER PRESETS API ────────────────────────────────────────────────────────
export const layerPresetsApi = {
  list: (projectId: string) => apiFetch(`/api/v1/projects/${projectId}/layer-presets`),
  create: (projectId: string, name: string, payload: any) =>
    apiFetch(`/api/v1/projects/${projectId}/layer-presets`, {
      method: 'POST',
      body: JSON.stringify({ name, payload }),
    }),
  update: (projectId: string, presetId: string, name: string, payload: any) =>
    apiFetch(`/api/v1/projects/${projectId}/layer-presets/${presetId}`, {
      method: 'PATCH',
      body: JSON.stringify({ name, payload }),
    }),
  delete: (projectId: string, presetId: string) =>
    apiFetch(`/api/v1/projects/${projectId}/layer-presets/${presetId}`, {
      method: 'DELETE',
    }),
}

// ── WEBSOCKET SETUP ──────────────────────────────────────────────────────────
export function getEventsWebSocketUrl(token: string) {
  const wsProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = BASE.replace(/^https?:\/\//, '')
  return `${wsProto}//${host}/api/v1/events?token=${encodeURIComponent(token)}`
}
