import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'
import './index.css'
import { TwinProvider } from './state/useTwin'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TwinProvider>
      <App />
    </TwinProvider>
  </StrictMode>,
)
