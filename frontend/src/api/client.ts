import axios from 'axios'
import { withBasePath } from '../utils/basePath'

const apiClient = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' },
})

// Attach JWT token from localStorage to every request
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem('lanlens_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// Redirect to login on 401
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('lanlens_token')
      localStorage.removeItem('lanlens_user')
      window.location.href = withBasePath('/login')
    }
    return Promise.reject(error)
  },
)

export default apiClient
