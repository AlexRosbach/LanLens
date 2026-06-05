import toast from 'react-hot-toast'

type ClientErrorPayload = {
  kind: string
  message: string
  path?: string
  source?: string
  status?: number
  endpoint?: string
}

let installed = false

function stringifyMessage(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (value instanceof Error) return value.message
  return 'Client-side UI error'
}

function trim(value: string, limit: number): string {
  return value.replace(/\s+/g, ' ').trim().slice(0, limit)
}

export function logClientError(payload: ClientErrorPayload) {
  const body = JSON.stringify({
    ...payload,
    message: trim(payload.message || 'Client-side UI error', 600),
    path: trim(payload.path || window.location.pathname, 300),
  })

  try {
    if (navigator.sendBeacon) {
      const blob = new Blob([body], { type: 'application/json' })
      if (navigator.sendBeacon('/api/client-errors', blob)) return
    }
  } catch {
    // Fall back to fetch below.
  }

  fetch('/api/client-errors', {
    method: 'POST',
    body,
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    keepalive: true,
  }).catch(() => {})
}

export function installClientErrorLogging() {
  if (installed) return
  installed = true

  const originalToastError = toast.error.bind(toast)
  toast.error = ((message: Parameters<typeof toast.error>[0], options?: Parameters<typeof toast.error>[1]) => {
    logClientError({
      kind: 'toast',
      message: stringifyMessage(message),
      source: 'toast.error',
    })
    return originalToastError(message, options)
  }) as typeof toast.error

  window.addEventListener('error', (event) => {
    logClientError({
      kind: 'runtime',
      message: event.message || stringifyMessage(event.error),
      source: event.filename ? `${event.filename}:${event.lineno}:${event.colno}` : 'window.error',
    })
  })

  window.addEventListener('unhandledrejection', (event) => {
    logClientError({
      kind: 'unhandledrejection',
      message: stringifyMessage(event.reason),
      source: 'window.unhandledrejection',
    })
  })
}
