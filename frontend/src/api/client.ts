import axios from 'axios'
import { withBasePath } from '../utils/basePath'
import { logClientError } from '../utils/clientErrorLogger'

const apiClient = axios.create({
  baseURL: '/api',
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
})

// Redirect to login on 401, but let auth/session bootstrap failures be handled by route guards
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    const requestUrl = String(error.config?.url ?? '')
    const loginPath = withBasePath('/login')
    const isAuthBootstrapCall = requestUrl.includes('/auth/me')
    const isClientErrorLogCall = requestUrl.includes('/client-errors')
    const alreadyOnLogin = window.location.pathname === loginPath

    if (!isClientErrorLogCall && !isAuthBootstrapCall) {
      const detail = error.response?.data?.detail
      logClientError({
        kind: 'api',
        message: typeof detail === 'string' ? detail : error.message || 'API request failed',
        path: window.location.pathname,
        status: error.response?.status,
        endpoint: requestUrl,
      })
    }

    if (error.response?.status === 401 && !isAuthBootstrapCall && !alreadyOnLogin) {
      window.location.href = loginPath
    }
    return Promise.reject(error)
  },
)

export default apiClient
