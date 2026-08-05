import './tokens.css'
import './preview-page.css'
import {
  AmbientBackground,
  GlassPanel,
  Card,
  MetricTile,
  Badge,
  Button,
  PageHeader,
  EmptyState,
  StatRow,
  type BadgeVariant,
} from './components'

interface Swatch {
  role: string
  hex: string
  varName: string
  usage: string
}

const PALETTE: Swatch[] = [
  { role: 'bg-base', hex: '#08090D', varName: '--v-bg-base', usage: 'App background' },
  { role: 'surface', hex: '#14161D', varName: '--v-surface', usage: 'Cards, tiles' },
  { role: 'surface-raised', hex: '#1C1F28', varName: '--v-surface-raised', usage: 'Raised surfaces' },
  { role: 'border', hex: '#262A35', varName: '--v-border', usage: 'Default borders' },
  { role: 'border-hover', hex: '#363B49', varName: '--v-border-hover', usage: 'Hover borders' },
  { role: 'cyan', hex: '#00E5D4', varName: '--v-cyan', usage: 'Primary — actual data, active nav, focus' },
  { role: 'violet', hex: '#B14BFF', varName: '--v-violet', usage: 'Secondary — predictions, ML' },
  { role: 'pink', hex: '#FF3D71', varName: '--v-pink', usage: 'Danger, critical' },
  { role: 'amber', hex: '#FFD84D', varName: '--v-amber', usage: 'Warning' },
  { role: 'green', hex: '#3DFFA3', varName: '--v-green', usage: 'Success, healthy' },
]

const BADGE_VARIANTS: BadgeVariant[] = ['success', 'warning', 'danger', 'info', 'neutral']

// Actual (solid, cyan) vs predicted (dashed, violet) revenue by event hour —
// inline SVG, no charting-library dependency for this static illustration.
const CHART_WIDTH = 460
const CHART_HEIGHT = 190
const PLOT_LEFT = 34
const PLOT_RIGHT = 8
const PLOT_TOP = 8
const PLOT_BOTTOM = 22
const PLOT_WIDTH = CHART_WIDTH - PLOT_LEFT - PLOT_RIGHT
const PLOT_HEIGHT = CHART_HEIGHT - PLOT_TOP - PLOT_BOTTOM

const Y_MAX = 45000
const Y_TICKS = [0, 15000, 30000, 45000]
const Y_TICK_LABELS = ['0', '15k', '30k', '45k']

const HOURS = ['18:00', '19:00', '20:00', '21:00', '22:00', '23:00', '00:00', '01:00']
const ACTUAL_REVENUE = [3800, 9200, 15600, 22400, 28900, 35200, 40500, 44990]
// Predicted line only starts once the forecast model has enough of the
// event to run on (hour index 3 / 21:00), same starting point as actual.
const PREDICTED_REVENUE = [22400, 27400, 32800, 38400, 43806]

function xForHour(index: number) {
  return PLOT_LEFT + (PLOT_WIDTH * index) / (HOURS.length - 1)
}

function yForValue(value: number) {
  return PLOT_TOP + PLOT_HEIGHT * (1 - value / Y_MAX)
}

const ACTUAL_POINTS = ACTUAL_REVENUE.map((v, i) => [xForHour(i), yForValue(v)])
const PREDICTED_POINTS = PREDICTED_REVENUE.map((v, i) => [xForHour(i + 3), yForValue(v)])

function toPolyline(points: number[][]) {
  return points.map(([x, y]) => `${x},${y}`).join(' ')
}

export default function DesignSystemPage() {
  return (
    <div className="vera-dark vds-page">
      <AmbientBackground />
      <div className="vds-shell">
        <PageHeader
          title="Vera Event — Design System"
          subtitle="Day 1 · tokens, components, preview. Nothing here is wired into the app yet."
          actions={
            <>
              <Button variant="secondary">Docs</Button>
              <Button variant="primary">Copy tokens.css</Button>
            </>
          }
        />

        {/* ── Glass chrome demo ─────────────────────────────────────────── */}
        <div className="vds-section">
          <h2 className="vds-section__title">Glass chrome (sidebar / header only)</h2>
          <p className="vds-section__desc">
            backdrop-filter is reserved for chrome that doesn't repeat or scroll. Data below
            uses solid Card surfaces instead.
          </p>
          <div className="vds-chrome-demo">
            <GlassPanel className="vds-sidebar-demo">
              <div className="vds-nav-item vds-nav-item--active">Dashboard</div>
              <div className="vds-nav-item">Events</div>
              <div className="vds-nav-item">Predictions</div>
              <div className="vds-nav-item">Reports</div>
              <div className="vds-nav-item">Warehouse</div>
            </GlassPanel>
            <GlassPanel className="vds-header-demo">
              <span className="vds-header-demo__title">Sundance Music Festival</span>
              <Badge variant="info">Live</Badge>
            </GlassPanel>
          </div>
        </div>

        {/* ── Palette ───────────────────────────────────────────────────── */}
        <div className="vds-section">
          <h2 className="vds-section__title">Palette</h2>
          <div className="vds-swatch-grid">
            {PALETTE.map((swatch) => (
              <div key={swatch.varName}>
                <div className="vds-swatch__chip" style={{ background: `var(${swatch.varName})` }} />
                <div className="vds-swatch__meta">
                  <span className="vds-swatch__role">{swatch.role}</span>
                  <span className="vds-swatch__hex">{swatch.hex}</span>
                  <span className="vds-swatch__hex">{swatch.usage}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* ── Metric tiles ──────────────────────────────────────────────── */}
        <div className="vds-section">
          <h2 className="vds-section__title">Metric tiles</h2>
          <div className="vds-metric-row">
            <MetricTile label="Revenue" value="€44,990" accent="cyan" />
            <MetricTile label="Drinks Served" value="3,951" accent="cyan" />
            <MetricTile label="Guests" value="1,171" accent="green" />
            <MetricTile label="Forecast" value="€43,806" accent="violet" />
            <MetricTile label="Confidence" value="70%" accent="amber" />
          </div>
        </div>

        {/* ── Badges & buttons ──────────────────────────────────────────── */}
        <div className="vds-section">
          <h2 className="vds-section__title">Badges</h2>
          <div className="vds-row">
            {BADGE_VARIANTS.map((variant) => (
              <Badge key={variant} variant={variant}>
                {variant}
              </Badge>
            ))}
          </div>
        </div>

        <div className="vds-section">
          <h2 className="vds-section__title">Buttons</h2>
          <div className="vds-row">
            <Button variant="primary">Primary</Button>
            <Button variant="secondary">Secondary</Button>
            <Button variant="ghost">Ghost</Button>
            <Button variant="primary" disabled>
              Disabled
            </Button>
          </div>
        </div>

        {/* ── Card + chart ──────────────────────────────────────────────── */}
        <div className="vds-section">
          <h2 className="vds-section__title">Card — actual vs. predicted revenue</h2>
          <Card>
            <StatRow
              items={[
                { label: 'Actual to date', value: '€44,990' },
                { label: 'Forecast', value: '€43,806' },
                { label: 'Confidence', value: '70%' },
              ]}
            />
            <svg
              viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
              className="vds-chart-svg"
              role="img"
              aria-label="Actual vs. predicted revenue by event hour"
            >
              {Y_TICKS.map((tick, i) => (
                <g key={tick}>
                  <line
                    x1={PLOT_LEFT}
                    x2={CHART_WIDTH - PLOT_RIGHT}
                    y1={yForValue(tick)}
                    y2={yForValue(tick)}
                    stroke="var(--v-border)"
                    strokeWidth={1}
                  />
                  <text
                    x={PLOT_LEFT - 8}
                    y={yForValue(tick) + 3}
                    textAnchor="end"
                    fontSize={10}
                    fill="var(--v-text-dim)"
                  >
                    {Y_TICK_LABELS[i]}
                  </text>
                </g>
              ))}
              {HOURS.map((hour, i) => (
                <text
                  key={hour}
                  x={xForHour(i)}
                  y={CHART_HEIGHT - 4}
                  textAnchor="middle"
                  fontSize={10}
                  fill="var(--v-text-dim)"
                >
                  {hour}
                </text>
              ))}
              <polyline
                points={toPolyline(ACTUAL_POINTS)}
                fill="none"
                stroke="var(--v-cyan)"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <polyline
                points={toPolyline(PREDICTED_POINTS)}
                fill="none"
                stroke="var(--v-violet)"
                strokeWidth={2}
                strokeDasharray="6 5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            <div className="vds-chart-legend">
              <span className="vds-chart-legend__item">
                <span className="vds-chart-legend__swatch" style={{ background: 'var(--v-cyan)' }} />
                Actual
              </span>
              <span className="vds-chart-legend__item">
                <span
                  className="vds-chart-legend__swatch"
                  style={{
                    background:
                      'repeating-linear-gradient(90deg, var(--v-violet) 0 6px, transparent 6px 11px)',
                  }}
                />
                Predicted
              </span>
            </div>
          </Card>
        </div>

        {/* ── Empty state ───────────────────────────────────────────────── */}
        <div className="vds-section">
          <h2 className="vds-section__title">Empty state</h2>
          <Card>
            <EmptyState
              headline="No events yet"
              body="Create your first event to start tracking revenue and drink forecasts."
              action={<Button variant="primary">Create event</Button>}
            />
          </Card>
        </div>
      </div>
    </div>
  )
}
