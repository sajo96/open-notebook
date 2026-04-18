'use client'

import type { AnnotationResponse } from '@/lib/types/api'

interface AnnotationOverlayProps {
    annotations: AnnotationResponse[]
}

function getStyle(annotation: AnnotationResponse) {
    const color = annotation.color || '#fef08a'

    if (annotation.annotation_type === 'underline') {
        return {
            backgroundColor: 'transparent',
            borderBottom: `2px solid ${color}`,
            borderRadius: 2,
        }
    }

    if (annotation.annotation_type === 'note') {
        return {
            backgroundColor: 'rgba(253, 224, 71, 0.28)',
            borderLeft: `3px solid ${color}`,
            borderRadius: 2,
        }
    }

    return {
        backgroundColor: color,
        opacity: 0.45,
        borderRadius: 2,
    }
}

export function AnnotationOverlay({ annotations }: AnnotationOverlayProps) {
    if (!annotations.length) return null

    return (
        <div className="pointer-events-none absolute inset-0">
            {annotations.map(annotation =>
                annotation.bounding_boxes.map((box, index) => (
                    <div
                        key={`${annotation.id}-${index}`}
                        className="absolute"
                        style={{
                            left: `${box.x1 * 100}%`,
                            top: `${box.y1 * 100}%`,
                            width: `${(box.x2 - box.x1) * 100}%`,
                            height: `${(box.y2 - box.y1) * 100}%`,
                            ...getStyle(annotation),
                        }}
                    />
                ))
            )}
        </div>
    )
}
