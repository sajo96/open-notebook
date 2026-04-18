'use client'

declare global {
    interface PromiseConstructor {
        withResolvers?<T>(): {
            promise: Promise<T>
            resolve: (value: T | PromiseLike<T>) => void
            reject: (reason?: unknown) => void
        }
    }

    interface SimpleDOMMatrixPoint {
        x: number
        y: number
        z?: number
        w?: number
    }

    interface SimpleDOMMatrix {
        a: number
        b: number
        c: number
        d: number
        e: number
        f: number
        m11: number
        m12: number
        m13: number
        m14: number
        m21: number
        m22: number
        m23: number
        m24: number
        m31: number
        m32: number
        m33: number
        m34: number
        m41: number
        m42: number
        m43: number
        m44: number
        is2D: boolean
        isIdentity: boolean
        multiplySelf(other?: unknown): SimpleDOMMatrix
        preMultiplySelf(other?: unknown): SimpleDOMMatrix
        inverse(): SimpleDOMMatrix
        translate(tx?: number, ty?: number, tz?: number): SimpleDOMMatrix
        scale(scaleX?: number, scaleY?: number, scaleZ?: number): SimpleDOMMatrix
        rotate(rotX?: number, rotY?: number, rotZ?: number): SimpleDOMMatrix
        transformPoint(point?: SimpleDOMMatrixPoint): SimpleDOMMatrixPoint
    }

    // eslint-disable-next-line no-var
    var DOMMatrix: (new (init?: unknown) => SimpleDOMMatrix) | undefined
    // eslint-disable-next-line no-var
    var structuredClone: ((value: unknown, options?: { transfer?: unknown[] }) => unknown) | undefined
    // eslint-disable-next-line no-var
    var WebKitCSSMatrix: (new (...args: unknown[]) => unknown) | undefined
}

function createMinimalDOMMatrix() {
    return class MinimalDOMMatrix {
        a = 1
        b = 0
        c = 0
        d = 1
        e = 0
        f = 0
        m11 = 1
        m12 = 0
        m13 = 0
        m14 = 0
        m21 = 0
        m22 = 1
        m23 = 0
        m24 = 0
        m31 = 0
        m32 = 0
        m33 = 1
        m34 = 0
        m41 = 0
        m42 = 0
        m43 = 0
        m44 = 1
        is2D = true
        isIdentity = true

        constructor(_init?: unknown) { }

        multiplySelf(_other?: unknown) {
            return this
        }

        preMultiplySelf(_other?: unknown) {
            return this
        }

        inverse() {
            return this
        }

        translate(_tx = 0, _ty = 0, _tz = 0) {
            return this
        }

        scale(_scaleX = 1, _scaleY = 1, _scaleZ = 1) {
            return this
        }

        rotate(_rotX = 0, _rotY = 0, _rotZ = 0) {
            return this
        }

        transformPoint(point: SimpleDOMMatrixPoint = { x: 0, y: 0, z: 0, w: 1 }) {
            return point
        }
    }
}

if (typeof Promise.withResolvers !== 'function') {
    Promise.withResolvers = function withResolvers<T>() {
        let resolve!: (value: T | PromiseLike<T>) => void
        let reject!: (reason?: unknown) => void

        const promise = new Promise<T>((res, rej) => {
            resolve = res
            reject = rej
        })

        return { promise, resolve, reject }
    }
}

if (typeof globalThis.structuredClone !== 'function') {
    globalThis.structuredClone = function structuredCloneFallback<T>(value: T): T {
        if (value === null || typeof value !== 'object') {
            return value
        }

        try {
            return JSON.parse(JSON.stringify(value)) as T
        } catch {
            return value
        }
    }
}

if (typeof globalThis.DOMMatrix === 'undefined') {
    if (typeof globalThis.WebKitCSSMatrix !== 'undefined') {
        globalThis.DOMMatrix = globalThis.WebKitCSSMatrix as unknown as typeof globalThis.DOMMatrix
    } else {
        globalThis.DOMMatrix = createMinimalDOMMatrix() as unknown as typeof globalThis.DOMMatrix
    }
}
