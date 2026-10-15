import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'

import AppRouter from './router'
import { initializeObservability, ObservabilityErrorBoundary } from '@/services/observability'

import './index.css'

initializeObservability()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ObservabilityErrorBoundary>
      <BrowserRouter basename={import.meta.env.BASE_URL}>
        <AppRouter />
      </BrowserRouter>
    </ObservabilityErrorBoundary>
  </StrictMode>,
)
