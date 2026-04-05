/**
 * Card — white surface container with standard border and padding.
 */
import { type ReactNode } from 'react'

interface CardProps {
  children: ReactNode
  className?: string
}

export function Card({ children, className = '' }: CardProps) {
  return (
    <div className={`bg-white border border-[#E2E8F0] rounded-lg p-4 ${className}`}>
      {children}
    </div>
  )
}
