import { useEffect, useState } from 'react'
import { APP_VERSION } from '../version'
import { settingsApi } from '../api/settings'

interface UpdateInfo {
  latestVersion: string
  releaseUrl: string
}

const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000
let dismissedVersion: string | null = null
let notifiedVersion: string | null = null

function parseVersionTuple(version: string): number[] | null {
  const match = version.trim().match(/^v?(\d+(?:\.\d+)*)/)
  if (!match) return null
  return match[1].split('.').map((part) => Number(part))
}

function isNewerVersion(latestVersion: string, currentVersion: string): boolean {
  const latest = parseVersionTuple(latestVersion)
  const current = parseVersionTuple(currentVersion)

  if (!latest || !current) {
    return Boolean(latestVersion) && latestVersion !== currentVersion
  }

  const maxLen = Math.max(latest.length, current.length)
  for (let i = 0; i < maxLen; i += 1) {
    const latestPart = latest[i] ?? 0
    const currentPart = current[i] ?? 0
    if (latestPart > currentPart) return true
    if (latestPart < currentPart) return false
  }

  return false
}

export function useUpdateCheck(): UpdateInfo | null {
  const [update, setUpdate] = useState<UpdateInfo | null>(null)

  useEffect(() => {
    async function check() {
      try {
        const data = await settingsApi.checkUpdate()
        const latest = data.latest_version
        const url = data.release_url

        if (data.update_available && latest && isNewerVersion(latest, APP_VERSION)) {
          const tag = `v${latest}`
          if (dismissedVersion !== tag) {
            setUpdate({ latestVersion: latest, releaseUrl: url })
          }
          if (notifiedVersion !== tag) {
            settingsApi.notifyUpdateAvailable().catch(() => {})
            notifiedVersion = tag
          }
        } else {
          setUpdate(null)
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
