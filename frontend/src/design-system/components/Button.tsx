import type { ButtonHTMLAttributes } from 'react'
import './components.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
}

/** primary = cyan fill / dark text · secondary = border only · ghost = text only */
export function Button({ variant = 'primary', className = '', children, ...rest }: ButtonProps) {
  return (
    <button className={`v-btn v-btn--${variant} ${className}`.trim()} {...rest}>
      {children}
    </button>
  )
}
