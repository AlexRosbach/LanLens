import { FormEvent, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import toast from 'react-hot-toast'
import { authApi } from '../api/auth'
import { useAuthStore } from '../store/authStore'
import Button from '../components/ui/Button'
import Input from '../components/ui/Input'
import { withBasePath } from '../utils/basePath'
import { useI18n } from '../i18n'

export default function ForcePasswordChange() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const { setForcePasswordChangeDone } = useAuthStore()
  const navigate = useNavigate()
  const { t } = useI18n()

  function strength(pw: string): { label: string; color: string; width: string } {
    if (pw.length === 0) return { label: '', color: '', width: '0%' }
    if (pw.length < 8) return { label: t('password_too_short'), color: 'bg-danger', width: '25%' }
    if (pw.length < 12) return { label: t('password_weak'), color: 'bg-warning', width: '50%' }
    if (/[A-Z]/.test(pw) && /[0-9]/.test(pw)) return { label: t('password_strong'), color: 'bg-success', width: '100%' }
    return { label: t('password_good'), color: 'bg-primary', width: '75%' }
  }

  const str = strength(next)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (next !== confirm) { toast.error(t('passwords_do_not_match')); return }
    if (next.length < 8) { toast.error(t('password_min_length')); return }
    setLoading(true)
    try {
      await authApi.changePassword(current, next)
      setForcePasswordChangeDone()
      toast.success(t('password_changed_welcome'))
      navigate('/')
    } catch (err: any) {
      toast.error(err?.response?.data?.detail ?? t('failed_to_change_password'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <img src={withBasePath('/logo.svg')} alt="LanLens" className="w-12 h-12 mb-3" />
          <h1 className="text-xl font-bold text-text-base">{t('set_password_title')}</h1>
          <p className="text-sm text-text-muted mt-1 text-center">
            {t('set_password_description')}
          </p>
        </div>

        <div className="bg-surface border border-border rounded-2xl p-6 shadow-2xl">
          <form onSubmit={handleSubmit} className="flex flex-col gap-4">
            <Input
              label={t('current_password')}
              type="password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              autoFocus
            />
            <div className="flex flex-col gap-1">
              <Input
                label={t('new_password')}
                type="password"
                placeholder={t('minimum_8_characters')}
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
              {next.length > 0 && (
                <div>
                  <div className="h-1 bg-surface2 rounded-full overflow-hidden mt-1">
                    <div className={`h-full ${str.color} transition-all`} style={{ width: str.width }} />
                  </div>
                  <p className={`text-xs mt-1 ${str.color.replace('bg-', 'text-')}`}>{str.label}</p>
                </div>
              )}
            </div>
            <Input
              label={t('confirm_new_password')}
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              error={confirm && next !== confirm ? t('passwords_do_not_match') : undefined}
            />
            <Button type="submit" loading={loading} className="w-full justify-center mt-1">
              {t('set_password_continue')}
            </Button>
          </form>
        </div>
      </div>
    </div>
  )
}
