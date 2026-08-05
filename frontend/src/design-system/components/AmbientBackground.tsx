import './components.css'

/**
 * Fixed, full-viewport ambient wash sitting behind page content on
 * --v-bg-base. Non-interactive — never intercepts clicks.
 */
export function AmbientBackground() {
  return (
    <div className="v-ambient" aria-hidden="true">
      <span className="v-ambient__blob v-ambient__blob--violet" />
      <span className="v-ambient__blob v-ambient__blob--cyan" />
      <span className="v-ambient__blob v-ambient__blob--pink" />
    </div>
  )
}
