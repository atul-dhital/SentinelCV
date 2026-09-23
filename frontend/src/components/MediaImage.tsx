'use client'

import React, { useEffect, useMemo, useState } from 'react'
import { getStaticMediaCandidates } from '@/lib/utils'

type MediaImageProps = Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src'> & {
    sources: Array<string | null | undefined>
    fallback?: React.ReactNode
}

export default function MediaImage({ sources, fallback = null, alt, onError, ...imgProps }: MediaImageProps) {
    const candidates = useMemo(() => getStaticMediaCandidates(...sources), [sources])
    const [activeIndex, setActiveIndex] = useState(0)

    useEffect(() => {
        setActiveIndex(0)
    }, [candidates.join('|')])

    const activeSrc = candidates[activeIndex]

    if (!activeSrc) {
        return <>{fallback}</>
    }

    return (
        <img
            {...imgProps}
            alt={alt}
            src={activeSrc}
            onError={(event) => {
                if (activeIndex < candidates.length - 1) {
                    setActiveIndex((previous) => Math.min(previous + 1, candidates.length - 1))
                    return
                }
                setActiveIndex(candidates.length)
                onError?.(event)
            }}
        />
    )
}
