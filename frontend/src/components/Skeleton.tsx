import React from 'react'

interface SkeletonProps {
    className?: string
    variant?: 'text' | 'circular' | 'rectangular'
}

export const Skeleton: React.FC<SkeletonProps> = ({ className = '', variant = 'rectangular' }) => {
    const baseClass = "animate-pulse bg-white/5"
    const variantClasses = {
        text: "h-4 w-full rounded-full",
        circular: "rounded-full",
        rectangular: "rounded-2xl"
    }

    return (
        <div className={`${baseClass} ${variantClasses[variant]} ${className}`} />
    )
}

export const CardSkeleton = () => (
    <div className="glass-card p-6 space-y-4">
        <Skeleton variant="circular" className="w-12 h-12" />
        <div className="space-y-2">
            <Skeleton variant="text" className="w-3/4" />
            <Skeleton variant="text" className="w-1/2" />
        </div>
    </div>
)

export const ListSkeleton = () => (
    <div className="space-y-4">
        {[1, 2, 3, 4].map((i) => (
            <div key={i} className="glass-card p-4 flex items-center gap-4">
                <Skeleton variant="rectangular" className="w-14 h-14" />
                <div className="flex-1 space-y-2">
                    <Skeleton variant="text" className="w-1/4" />
                    <Skeleton variant="text" className="w-1/2" />
                </div>
            </div>
        ))}
    </div>
)
