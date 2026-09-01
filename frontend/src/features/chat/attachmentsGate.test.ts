/**
 * Chat attachments are DISABLED — honestly, not silently.
 *
 * Production has no object storage (no S3_* variables; storage defaults
 * to localhost:9000). Uploads always failed at the browser PUT after
 * the presign had already created an orphaned chat_attachments row.
 * With chat receiving no further investment, the control is disabled
 * visibly: the gate below blocks the upload BEFORE any network call
 * (no presign, no orphan row) and supplies the message the user sees.
 * Revival checklist lives in docs/post-sundance-backlog.md.
 */
import { describe, expect, it } from 'vitest'

import {
  ATTACHMENTS_DISABLED_MESSAGE,
  ATTACHMENTS_ENABLED,
  attachmentUploadBlockedReason,
} from './useAttachments'

describe('attachments gate', () => {
  it('is disabled until object storage exists', () => {
    expect(ATTACHMENTS_ENABLED).toBe(false)
  })

  it('blocks with a plain, non-technical message — not a silent no-op', () => {
    const reason = attachmentUploadBlockedReason()
    expect(reason).toBe(ATTACHMENTS_DISABLED_MESSAGE)
    // Audience is a non-technical reader: the exact approved wording,
    // stating the fact without sounding broken.
    expect(reason).toBe('Attachments are unavailable.')
    // No developer jargon on a client-facing surface.
    expect(reason).not.toMatch(/S3_|localhost|MinIO|deployment|environment|configur/i)
  })
})
