'use client'

import React from 'react'

type Props = {
    checked: boolean
    onCheckedChange: (next: boolean) => void
    disabled?: boolean
    label: string
    description?: string
    size?: 'sm' | 'md'
    className?: string
}

export function Switch({ checked, onCheckedChange, disabled, label, description, size = 'md', className = '' }: Props) {
    const handleToggle = () => { if (!disabled) onCheckedChange(!checked) }

    const handleKey = (e: React.KeyboardEvent<HTMLButtonElement>) => {
        if (disabled) return
        if (e.key === ' ' || e.key === 'Enter') {
            e.preventDefault()
            onCheckedChange(!checked)
        }
        if (e.key === 'ArrowLeft') { e.preventDefault(); onCheckedChange(false) }
        if (e.key === 'ArrowRight') { e.preventDefault(); onCheckedChange(true) }
    }

    const track = size === 'sm' ? 'w-8 h-4' : 'w-10 h-5'
    const thumb = size === 'sm' ? 'w-3 h-3' : 'w-4 h-4'
    const translate = size === 'sm' ? 'translate-x-4' : 'translate-x-5'

    return (
        <button
            type="button"
            role="switch"
            aria-checked={checked}
            aria-label={label}
            aria-describedby={description ? `${label}-desc` : undefined}
            disabled={disabled}
            onClick={handleToggle}
            onKeyDown={handleKey}
            className={`relative inline-flex items-center rounded-full transition-colors ${track} ${
                checked ? 'bg-brand-500' : 'bg-white/10'
            } ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'} focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-950 ${className}`}
        >
            <span
                aria-hidden="true"
                className={`${thumb} inline-block rounded-full bg-white shadow transform transition-transform ${
                    checked ? translate : 'translate-x-0.5'
                }`}
            />
        </button>
    )
}

export default Switch
