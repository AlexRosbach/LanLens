import { useEffect, useState } from 'react'
import { APP_VERSION, GITHUB_REPO } from '../version'
import { settingsApi } from '../api/settings'

interface UpdateInfo {
  latestVersion: string
  releaseUrl: string
}

function parseSemver(tag: string): [number, number, number] {
  const parts = tag.replace(/^v/, '').split('.').map(Number)
  return [parts[0] ?? 0, parts[1] ?? 0, parts[2] ?? 0]
}

function isNewer(latest: string, current: string): boolean {
  const [lMaj, lMin, lPat] = parseSemver(latest)
  const [cMaj, cMin, cPat] = parseSemver(current)
  if (lMaj !== cMaj) return lMaj > cMaj
  if (lMin !== cMin) return lMin > cMin
  return lPat > cPat
}

const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000
let dismissedVersion: string | null = null
let notifiedVersion: string | null = null

export function useUpdateCheck(): UpdateInfo | null {
  const [update, setUpdate] = useState<UpdateInfo | null>(null)

  useEffect(() => {
    async function check() {
      try {
        const res = await fetch(
          `https://api.github.com/repos/${GITHUB_REPO}/releases/latest`,
          { headers: { Accept: 'application/vnd.github+json' } }
        )
        if (!res.ok) return
        const data = await res.json()
        const tag: string = data.tag_name ?? ''
        const url: string = data.html_url ?? `https://github.com/${GITHUB_REPO}/releases/latest`

        if (isNewer(tag, APP_VERSION)) {
          if (dismissedVersion !== tag) {
            setUpdate({ latestVersion: tag.replace(/^v/, ''), releaseUrl: url })
          }
          if (notifiedVersion !== tag) {
            settingsApi.notifyUpdateAvailable().catch(() => {})
            notifiedVersion = tag
          }
        }
      } catch {
        // best effort
      }
    }

    check()
    const interval = setInterval(check, CHECK_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [])

  return update
}

export function dismissUpdate(version: string) {
  dismissedVersion = `v${version}`
}
