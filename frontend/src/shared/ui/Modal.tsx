/**
 * Modal — accessible dialog overlay with backdrop dismiss and close button.
 */
import { type ReactNode } from 'react'

interface ModalProps {
  isOpen: boolean
  onClose: () => void
  title: string
  children: ReactNode
}

export function Modal({ isOpen, onClose, title, children }: ModalProps) {
  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative bg-white rounded-lg shadow-xl p-6 w-full max-w-md z-10">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-[#1A202C]">{title}</h2>
          <button onClick={onClose} className="text-[#4A5568] hover:text-[#1A202C] text-xl leading-none">
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
