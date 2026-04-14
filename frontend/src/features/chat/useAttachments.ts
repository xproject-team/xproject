/**
 * Hook for uploading file attachments to chat channels.
 *
 * Flow per file:
 *   1. POST /chat/attachments/presign  → { attachment_id, upload_url }
 *   2. PUT file directly to MinIO via upload_url
 *   3. Return attachment_id to caller
 *
 * The caller passes attachment_ids[] when posting the message.
 */
import { useState } from 'react'

import { api } from '@/lib/api'


export interface AttachmentPreview {
  id:        string         // attachment_id from backend
  filename:  string
  size:      number
  type:      string         // MIME
}

interface PresignResponse {
  attachment_id:      string
  upload_url:         string
  object_key:         string
  expires_in_seconds: number
}


/** Use inside a component that needs to upload files attached to a message. */
export function useAttachmentUpload(channelId: string) {
  const [pending,   setPending]   = useState<AttachmentPreview[]>([])
  const [uploading, setUploading] = useState<boolean>(false)
  const [error,     setError]     = useState<string | null>(null)

  /** Upload a file: presign → PUT → return preview to track. */
  async function upload(file: File): Promise<AttachmentPreview | null> {
    setError(null)
    setUploading(true)
    try {
      // Step 1: presign
      const presignRes = await api.post<PresignResponse>('/chat/attachments/presign', {
        channel_id:   channelId,
        filename:     file.name,
        content_type: file.type || 'application/octet-stream',
        size_bytes:   file.size,
      })
      const { attachment_id, upload_url } = presignRes.data

      // Step 2: PUT directly to MinIO. We use raw fetch (not axios) because
      // we need to bypass axios's default JSON body interceptor — we want the
      // raw file bytes in the request body.
      const putRes = await fetch(upload_url, {
        method:  'PUT',
        body:    file,
        headers: { 'Content-Type': file.type || 'application/octet-stream' },
      })
      if (!putRes.ok) {
        throw new Error(`Upload failed: ${putRes.status} ${putRes.statusText}`)
      }

      // Step 3: track the preview
      const preview: AttachmentPreview = {
        id:       attachment_id,
        filename: file.name,
        size:     file.size,
        type:     file.type || 'application/octet-stream',
      }
      setPending((prev) => [...prev, preview])
      return preview
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Upload failed'
      setError(msg)
      return null
    } finally {
      setUploading(false)
    }
  }

  /** Remove a pending attachment (user clicked the X before sending). */
  function remove(id: string) {
    setPending((prev) => prev.filter((a) => a.id !== id))
  }

  /** Clear all pending attachments (called after successful message send). */
  function clear() {
    setPending([])
  }

  return { pending, uploading, error, upload, remove, clear }
}


/** Pretty file size: 1234 → "1.2 KB" */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}


/** True if MIME indicates an image we can preview inline. */
export function isImageType(type: string): boolean {
  return type.startsWith('image/')
}
