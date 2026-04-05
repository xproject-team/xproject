/**
 * App root — mounts providers and the router outlet.
 * All global state providers are wired in providers.tsx.
 */
import { Providers } from './providers'
import { AppRoutes } from './routes'

export default function App() {
  return (
    <Providers>
      <AppRoutes />
    </Providers>
  )
}
