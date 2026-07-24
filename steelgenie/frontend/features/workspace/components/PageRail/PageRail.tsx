import React, { useState } from 'react'
import { PageCard } from './PageCard'
import { uploadDrawing } from '../../../../lib/api'
import { useWorkspaceStore } from '../../../../lib/stores/workspaceStore'
import { Upload, FileText, ArrowRight } from 'lucide-react'
import { toast } from 'sonner'
import { Spinner } from '../../../../components/ui/Spinner'

interface Page {
  id: string
  drawing_id: string
  idx: number
  sheet_no: string | null
  title: string | null
  scale_num: number | null
  scale_label: string | null
  tos_ft: number | null
  status: string
  thumb_url: string | null
  is_foundation_plan?: boolean | null
}

interface PageRailProps {
  projectId: string
  pages: Page[]
  isLoading: boolean
  refetchWorkspace: () => void
  onUpdatePage: (pageId: string, data: any) => Promise<any>
  onExtract: (page: Page) => void
  extractingPageId: string | null
  extractProgress: { pct: number; msg: string } | null
}

export function PageRail({
  projectId,
  pages,
  isLoading,
  refetchWorkspace,
  onUpdatePage,
  onExtract,
  extractingPageId,
  extractProgress,
}: PageRailProps) {
  const { currentPageId, setCurrentPage, setScale, dirtyPageIds } = useWorkspaceStore()
  const [uploading, setUploading] = useState(false)

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const ext = file.name.toLowerCase().split('.').pop()
    if (!['pdf', 'jpg', 'jpeg', 'png'].includes(ext || '')) {
      toast.error('Only PDF, JPG, or PNG files are accepted')
      return
    }

    setUploading(true)
    toast.info('Uploading plan drawing...')
    try {
      await uploadDrawing(projectId, file)
      toast.success('Drawing uploaded. Ingestion job started.')
      refetchWorkspace()
    } catch (err: any) {
      toast.error(err.message || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const handleSelectPage = (page: Page) => {
    console.log('[PageRail] handleSelectPage called for page:', page.id, 'index:', page.idx)
    setCurrentPage(page.id, page.idx)
    setScale(page.scale_label, page.scale_num)
  }

  return (
    <div
      style={{
        width: '100%',
        backgroundColor: '#111827',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        flexShrink: 0,
      }}
    >
      {/* Upload button container */}
      <div
        style={{
          padding: '16px',
          borderBottom: '1px solid rgba(59, 130, 246, 0.08)',
        }}
      >
        <label
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '8px',
            padding: '10px',
            backgroundColor: 'rgba(59, 130, 246, 0.08)',
            border: '1px dashed rgba(59, 130, 246, 0.3)',
            borderRadius: '8px',
            color: '#60A5FA',
            fontSize: '13px',
            fontWeight: 600,
            cursor: uploading ? 'not-allowed' : 'pointer',
            transition: 'all 0.2s',
          }}
        >
          {uploading ? (
            <>
              <Spinner size="sm" />
              <span>Uploading...</span>
            </>
          ) : (
            <>
              <Upload size={14} />
              <span>Upload PDF Plan</span>
            </>
          )}
          <input
            type="file"
            accept=".pdf,.jpg,.jpeg,.png"
            onChange={handleUpload}
            disabled={uploading}
            style={{ display: 'none' }}
          />
        </label>
      </div>

      {/* Pages list scroll area */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
        }}
      >
        {isLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '24px' }}>
            <Spinner size="md" />
          </div>
        ) : pages.length === 0 ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '32px 16px',
              textAlign: 'center',
              color: '#475569',
            }}
          >
            <FileText size={32} style={{ marginBottom: '8px' }} />
            <span style={{ fontSize: '12px', fontWeight: 600 }}>No sheets yet</span>
            <span style={{ fontSize: '11px', marginTop: '4px' }}>Upload a PDF drawing above to start</span>
          </div>
        ) : (
          pages.map((page, i) => (
            <PageCard
              key={page.id}
              page={page}
              displayNumber={i + 1}
              isActive={currentPageId === page.id}
              isExtracting={extractingPageId === page.id}
              extractProgress={extractingPageId === page.id ? extractProgress : null}
              isDirty={dirtyPageIds.has(page.id)}
              onClick={() => handleSelectPage(page)}
              onUpdatePage={onUpdatePage}
              onExtract={onExtract}
            />
          ))
        )}
      </div>
    </div>
  )
}
