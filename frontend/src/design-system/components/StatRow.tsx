import './components.css'

interface StatRowItem {
  label: string
  value: string
}

interface StatRowProps {
  items: StatRowItem[]
}

export function StatRow({ items }: StatRowProps) {
  return (
    <div className="v-stat-row">
      {items.map((item) => (
        <div className="v-stat-row__item" key={item.label}>
          <span className="v-label">{item.label}</span>
          <span className="v-stat-row__value">{item.value}</span>
        </div>
      ))}
    </div>
  )
}
