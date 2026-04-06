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

export function useUpdateCheck(): UpdateInfo | null {
  const [update, setUpdate] = useState<UpdateInfo | null>(null)

  useEffect(() => {
    async function check() {
      try {
        const data = await settingsApi.checkUpdate()
        const latest = data.latest_version
        const url = data.release_url

        if (data.update_available && latest && latest !== APP_VERSION) {
          const tag = `v${latest}`
          if (dismissedVersion !== tag) {
            setUpdate({ latestVersion: latest, releaseUrl: url })
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
