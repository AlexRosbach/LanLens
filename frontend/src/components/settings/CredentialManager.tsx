import { useEffect, useState } from 'react'
import toast from 'react-hot-toast'
import { credentialsApi, type Credential } from '../../api/credentials'
import { useI18n } from '../../i18n'
import Button from '../ui/Button'
import Badge from '../ui/Badge'
import CredentialModal from './CredentialModal'
import Input from '../ui/Input'

interface Props {
  onCredentialsChange?: (creds: Credential[]) => void
}

export default function CredentialManager({ onCredentialsChange }: Props = {}) {
  const { t } = useI18n()
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [showModal, setShowModal] = useState(false)
  const [editTarget, setEditTarget] = useState<Credential | null>(null)
  const [testIp, setTestIp] = useState<Record<number, string>>({})
  const [testingId, setTestingId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)

  const updateCreds = (creds: Credential[]) => {
    setCredentials(creds)
    onCredentialsChange?.(creds)
  }

  const load = async () => {
    try {
      const resp = await credentialsApi.list()
      updateCreds(resp.data)
    } catch {
      toast.error('Failed to load credentials')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleDelete = async (cred: Credential) => {
    if (!confirm(`Delete credential "${cred.name}"?`)) return
    try {
      await credentialsApi.delete(cred.id)
      updateCreds(credentials.filter((c) => c.id !== cred.id))
      toast.success('Credential deleted')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg || t('credential_delete_in_use'))
    }
  }

  const handleTest = async (cred: Credential) => {
    const ip = testIp[cred.id]?.trim()
    if (!ip) { toast.error(t('credential_test_target_ip') + ' required'); return }
    setTestingId(cred.id)
    try {
      const resp = await credentialsApi.test(cred.id, ip)
      if (resp.data.success) {
        toast.success(`${t('credential_test_success')} (${resp.data.latency_ms} ms)`)
      } else {
        toast.error(`${t('credential_test_failed')}: ${resp.data.message}`)
      }
    } catch {
      toast.error(t('credential_test_failed'))
    } finally {
      setTestingId(null)
    }
  }

  const handleSaved = (cred: Credential) => {
    const next = (() => {
      const idx = credentials.findIndex((c) => c.id === cred.id)
      if (idx >= 0) {
        const arr = [...credentials]; arr[idx] = cred; return arr
      }
      return [...credentials, cred]
    })()
    updateCreds(next)
    setShowModal(false)
    setEditTarget(null)
  }

  if (loading) {
    return <p className="text-sm text-text-subtle">{t('deep_scan_running')}</p>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-text-muted">
          {credentials.length === 0 ? t('no_credentials') : `${credentials.length} credential(s)`}
        </p>
        <Button size="sm" onClick={() => { setEditTarget(null); setShowModal(true) }}>
          {t('add_credential')}
        </Button>
      </div>

      {credentials.map((cred) => (
        <div key={cred.id} className="border border-border rounded-xl p-4 space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-medium text-text-base">{cred.name}</span>
              <Badge variant={cred.credential_type === 'linux_ssh' ? 'success' : 'primary'}>
                {cred.credential_type === 'linux_ssh'
                  ? t('credential_type_linux_ssh')
                  : t('credential_type_windows_winrm')}
              </Badge>
              {cred.auth_method === 'key' && (
                <Badge variant="warning">🔑 SSH Key</Badge>
              )}
              <span className="text-sm text-text-muted">{cred.username}</span>
            </div>
            <div className="flex items-center gap-1 shrink-0">
              <button
                onClick={() => { setEditTarget(cred); setShowModal(true) }}
                className="text-text-subtle hover:text-primary p-1.5 rounded-lg hover:bg-surface2 transition-colors"
                title="Edit"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
              </button>
              <button
                onClick={() => handleDelete(cred)}
                className="text-text-subtle hover:text-danger p-1.5 rounded-lg hover:bg-danger-dim transition-colors"
                title="Delete"
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                </svg>
              </button>
            </div>
          </div>

          {cred.description && (
            <p className="text-xs text-text-subtle">{cred.description}</p>
          )}

          {/* Test row */}
          <div className="flex items-center gap-2">
            <div className="flex-1">
              <Input
                placeholder={t('credential_test_target_ip')}
                value={testIp[cred.id] ?? ''}
                onChange={(e) =>
                  setTestIp((prev) => ({ ...prev, [cred.id]: e.target.value }))
                }
                size={20}
              />
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => handleTest(cred)}
              loading={testingId === cred.id}
            >
              {t('credential_test')}
            </Button>
          </div>
        </div>
      ))}

      {showModal && (
        <CredentialModal
          credential={editTarget}
          onClose={() => { setShowModal(false); setEditTarget(null) }}
          onSaved={handleSaved}
        />
      )}
    </div>
  )
}
