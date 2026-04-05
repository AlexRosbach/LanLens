import { useEffect, useState } from 'react'
import { APP_VERSION, GITHUB_REPO } from '../version'
import { settingsApi } from '../api/settings'

interface UpdateInfo {
  latestVersion: string
  releaseUrl: string
}

/** Parse "v1.2.3" or "1.2.3" into [major, minor, patch] */
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

const DISMISS_KEY = 'lanlens_update_dismissed'
const NOTIFIED_KEY = 'lanlens_update_notified'
const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000 // re-check every 6 hours

export function useUpdateCheck(): UpdateInfo | null {
  const [update, setUpdate] = useState<UpdateInfo | null>(null)

  useEffect(() => {
    const dismissed = localStorage.getItem(DISMISS_KEY)

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
          // Only show if the user hasn't dismissed this exact version
          if (dismissed !== tag) {
            setUpdate({ latestVersion: tag.replace(/^v/, ''), releaseUrl: url })
          }
          // Send Telegram notification once per version (backend checks if enabled)
          const notifiedVersion = localStorage.getItem(NOTIFIED_KEY)
          if (notifiedVersion !== tag) {
            settingsApi.notifyUpdateAvailable().catch(() => {})
            localStorage.setItem(NOTIFIED_KEY, tag)
          }
        }
      } catch {
        // Silently ignore network errors — update check is best-effort
      }
    }

    check()
    const interval = setInterval(check, CHECK_INTERVAL_MS)
    return () => clearInterval(interval)
  }, [])

  return update
}

export function dismissUpdate(version: string) {
  localStorage.setItem(DISMISS_KEY, `v${version}`)
}
