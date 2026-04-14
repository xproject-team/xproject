/**
 * Paperclip button + hidden file input + pending-attachment preview chips.
 * Sits next to the composer textarea. Files are uploaded immediately on pick.
 */
import { useRef } from 'react'

import {
  formatBytes,
  isImageType,
  type AttachmentPreview,
} from './useAttachments'


interface AttachmentPickerProps {
  channelId: string
  pending:   AttachmentPreview[]
  uploading: boolean
  error:     string | null
  onPick:    (file: File) => void
  onRemove:  (id: string) => void
}


export function AttachmentPicker({
  pending,
  uploading,
  error,
  onPick,
  onRemove,
}: AttachmentPickerProps) {
  const inputRef = useRef<HTMLInputElement | null>(null)

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) onPick(file)
    // Reset the input so picking the same file twice still triggers onChange
    e.target.value = ''
  }

  return (
    <div className="flex flex-col gap-1.5">
      {/* Pending chips row */}
      {pending.length > 0 && (
        <div className="flex flex-wrap gap-1.5 px-1">
          {pending.map((att) => (
            <div
              key={att.id}
              className="flex items-center gap-1.5 px-2 py-1 bg-[#F0F4F8] border border-[#E2E8F0] rounded-lg text-xs"
            >
              {isImageType(att.type) ? (
                <svg className="w-3.5 h-3.5 text-[#1E5A8D]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5 text-[#4A5568]" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              )}
              <span className="font-medium text-[#1A202C] truncate max-w-[160px]">{att.filename}</span>
              <span className="text-[#A0AEC0]">{formatBytes(att.size)}</span>
              <button
                onClick={() => onRemove(att.id)}
                className="ml-1 text-[#A0AEC0] hover:text-[#E74C3C]"
                title="Remove"
                type="button"
              >
                <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth={2.5} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Error display */}
      {error && (
        <p className="text-xs text-[#E74C3C] px-1">⚠ {error}</p>
      )}

      {/* Paperclip button */}
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        title="Attach file (max 25MB)"
        className="self-start p-2 text-[#A0AEC0] hover:text-[#1E5A8D] disabled:opacity-40 transition-colors"
      >
        {uploading ? (
          <svg className="w-5 h-5 animate-spin" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
        ) : (
          <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
        )}
      </button>

      {/* Hidden file input */}
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        onChange={handleFileChange}
      />
    </div>
  )
}
