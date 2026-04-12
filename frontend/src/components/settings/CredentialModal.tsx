import { useState } from 'react'
import toast from 'react-hot-toast'
import { credentialsApi, type Credential, type CredentialType, type AuthMethod } from '../../api/credentials'
import Modal from '../ui/Modal'
import Input from '../ui/Input'
import Button from '../ui/Button'
import { useI18n } from '../../i18n'

interface Props {
  credential: Credential | null
  onClose: () => void
  onSaved: (cred: Credential) => void
}

export default function CredentialModal({ credential, onClose, onSaved }: Props) {
  const { t } = useI18n()
  const isEdit = credential !== null

  const [name, setName] = useState(credential?.name ?? '')
  const [type, setType] = useState<CredentialType>(credential?.credential_type ?? 'linux_ssh')
  const [authMethod, setAuthMethod] = useState<AuthMethod>(credential?.auth_method ?? 'password')
  const [username, setUsername] = useState(credential?.username ?? '')
  const [secret, setSecret] = useState('')
  const [description, setDescription] = useState(credential?.description ?? '')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!name.trim()) { toast.error(t('credential_name') + ' required'); return }
    if (!username.trim()) { toast.error(t('credential_username') + ' required'); return }
    if (!isEdit && !secret.trim()) { toast.error(t('credential_secret') + ' required'); return }

    setSaving(true)
    try {
      let saved: Credential
      if (isEdit) {
        const resp = await credentialsApi.update(credential.id, {
          name: name.trim(),
          credential_type: type,
          auth_method: authMethod,
          username: username.trim(),
          ...(secret.trim() ? { secret: secret.trim() } : {}),
          description: description.trim() || undefined,
        })
        saved = resp.data
      } else {
        const resp = await credentialsApi.create({
          name: name.trim(),
          credential_type: type,
          auth_method: authMethod,
          username: username.trim(),
          secret: secret.trim(),
          description: description.trim() || undefined,
        })
        saved = resp.data
      }
      onSaved(saved)
      toast.success(t('save_credential') + ' ✓')
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail
      toast.error(msg || 'Failed to save credential')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={isEdit ? t('credential_name') : t('add_credential')}
    >
      <div className="space-y-4">
        <Input
          label={t('credential_name')}
          value={name}
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />

        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-text-muted">{t('credential_type')}</label>
          <select
            className="input-field"
            value={type}
            onChange={(e) => {
              const newType = e.target.value as CredentialType
              setType(newType)
              // Windows WinRM always uses password
              if (newType === 'windows_winrm') setAuthMethod('password')
            }}
          >
            <option value="linux_ssh">{t('credential_type_linux_ssh')}</option>
            <option value="windows_winrm">{t('credential_type_windows_winrm')}</option>
          </select>
        </div>

        {type === 'linux_ssh' && (
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-text-muted">{t('credential_auth_method')}</label>
            <div className="flex gap-3">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="auth_method"
                  value="password"
                  checked={authMethod === 'password'}
                  onChange={() => setAuthMethod('password')}
                  className="accent-primary"
                />
                <span className="text-sm text-text-base">{t('credential_auth_password')}</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="radio"
                  name="auth_method"
                  value="key"
                  checked={authMethod === 'key'}
                  onChange={() => setAuthMethod('key')}
                  className="accent-primary"
                />
                <span className="text-sm text-text-base">{t('credential_auth_key')}</span>
              </label>
            </div>
          </div>
        )}

        <Input
          label={t('credential_username')}
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="off"
        />

        {authMethod === 'key' ? (
          <div className="flex flex-col gap-1">
            <label className="text-sm font-medium text-text-muted">{t('credential_private_key')}</label>
            <textarea
              className="input-field font-mono text-xs min-h-[120px] resize-y"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
              placeholder={isEdit ? t('credential_secret_placeholder') : '-----BEGIN OPENSSH PRIVATE KEY-----\n...'}
              autoComplete="off"
              spellCheck={false}
            />
            <p className="text-xs text-text-subtle">Paste the full PEM private key (RSA, Ed25519, ECDSA). The key is stored encrypted.</p>
          </div>
        ) : (
          <Input
            label={t('credential_secret')}
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder={isEdit ? t('credential_secret_placeholder') : undefined}
            autoComplete="new-password"
          />
        )}

        <Input
          label={t('credential_description')}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />

        <div className="flex justify-end gap-2 pt-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSave} loading={saving}>{t('save_credential')}</Button>
        </div>
      </div>
    </Modal>
  )
}
