import axios from 'axios'
import { withBasePath } from '../utils/basePath'

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
    const alreadyOnLogin = window.location.pathname === loginPath

    if (error.response?.status === 401 && !isAuthBootstrapCall && !alreadyOnLogin) {
      window.location.href = loginPath
    }
    return Promise.reject(error)
  },
)

export default apiClient
