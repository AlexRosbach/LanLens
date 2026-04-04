import React from 'react'
import ReactDOM from 'react-dom/client'
import { Toaster } from 'react-hot-toast'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
    <Toaster
      position="top-right"
      toastOptions={{
        style: {
          background: '#1a1d2e',
          color: '#e2e8f0',
          border: '1px solid #2d3152',
          borderRadius: '10px',
          fontSize: '14px',
        },
        success: { iconTheme: { primary: '#22c55e', secondary: '#1a1d2e' } },
        error: { iconTheme: { primary: '#ef4444', secondary: '#1a1d2e' } },
      }}
    />
  </React.StrictMode>,
)
