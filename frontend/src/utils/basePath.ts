export function getBasePath(): string {
  const base = import.meta.env.BASE_URL || '/'
  if (!base || base === '/') return ''
  return base.endsWith('/') ? base.slice(0, -1) : base
}

export function withBasePath(path: string): string {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  const base = getBasePath()
  return base ? `${base}${normalizedPath}` : normalizedPath
}
