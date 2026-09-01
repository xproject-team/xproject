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


/**
 * Attachments are DISABLED until object storage exists.
 *
 * No environment configures S3_* variables, so presigned URLs point at
 * a default endpoint nothing serves: every upload failed at the browser
 * PUT — after the presign had already written an orphaned
 * chat_attachments row. Chat receives no further investment (client
 * ruling), so the control is disabled visibly instead: the gate blocks
 * BEFORE any network call, with a message the user actually sees.
 * Revival: configure object storage (see docs/post-sundance-backlog.md)
 * and flip this flag.
 */
export const ATTACHMENTS_ENABLED = false

// Wording approved 2026-09-01 for a non-technical audience: state the
// fact plainly, no jargon, nothing that sounds broken. (UI is
// English-only today; the Italian variant 'Gli allegati non sono
// disponibili.' is recorded for whenever localization exists.)
export const ATTACHMENTS_DISABLED_MESSAGE = 'Attachments are unavailable.'

/** The pre-flight gate `upload()` consults FIRST. Returns the honest,
 *  user-readable reason uploads are blocked, or null when allowed. */
export function attachmentUploadBlockedReason(): string | null {
  return ATTACHMENTS_ENABLED ? null : ATTACHMENTS_DISABLED_MESSAGE
}


/** Use inside a component that needs to upload files attached to a message. */
export function useAttachmentUpload(channelId: string) {
  const [pending,   setPending]   = useState<AttachmentPreview[]>([])
  const [uploading, setUploading] = useState<boolean>(false)
  const [error,     setError]     = useState<string | null>(null)

  /** Upload a file: presign → PUT → return preview to track. */
  async function upload(file: File): Promise<AttachmentPreview | null> {
    // Gate before ANY network call: no presign request, so no orphaned
    // attachment row — and an honest message instead of a dead control.
    const blocked = attachmentUploadBlockedReason()
    if (blocked) {
      setError(blocked)
      return null
    }
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
