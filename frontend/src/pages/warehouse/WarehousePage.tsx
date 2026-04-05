import { useState, useMemo, useCallback } from 'react'
import { MOCK_WAREHOUSE_ITEMS, MOCK_WAREHOUSE_SCANS, MOCK_BARS } from '@/lib/mockData'
import type { WarehouseItem, ProductCategory } from '@/lib/mockData'

// ─── Constants ────────────────────────────────────────────────────────────────

const CATEGORY_ORDER: ProductCategory[] = ['Spirits', 'Beer', 'Wine', 'Mixers', 'Other']

const CATEGORY_CFG: Record<ProductCategory, string> = {
  Spirits: 'bg-purple-100 text-purple-700 border border-purple-200',
  Beer:    'bg-yellow-100 text-yellow-700 border border-yellow-200',
  Wine:    'bg-pink-100 text-pink-700 border border-pink-200',
  Mixers:  'bg-blue-100 text-blue-700 border border-blue-200',
  Other:   'bg-gray-100 text-[#4A5568] border border-gray-200',
}

const UNIT_CFG: Record<string, string> = {
  bottles: 'bg-[#F7FAFC] text-[#4A5568] border border-[#E2E8F0]',
  cases:   'bg-indigo-50 text-indigo-700 border border-indigo-200',
  kegs:    'bg-amber-50 text-amber-700 border border-amber-200',
}

// Bar name lookup
const BAR_BY_ID = Object.fromEntries(MOCK_BARS.map((b) => [b.id, b.name]))

// ─── Sort helpers ─────────────────────────────────────────────────────────────

type SortField = keyof Pick<WarehouseItem, 'product_name' | 'brand' | 'category' | 'quantity_in_warehouse' | 'allocated_to_event'>
type SortDir   = 'asc' | 'desc'

function sortItems(items: WarehouseItem[], field: SortField, dir: SortDir): WarehouseItem[] {
  return [...items].sort((a, z) => {
    const av = a[field]
    const zv = z[field]
    const cmp = typeof av === 'number' && typeof zv === 'number'
      ? av - zv
      : String(av).localeCompare(String(zv))
    return dir === 'asc' ? cmp : -cmp
  })
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function SortIcon({ field, active, dir }: { field: string; active: boolean; dir: SortDir }) {
  return (
    <span className={`ml-1 inline-block ${active ? 'text-[#1E5A8D]' : 'text-[#CBD5E0]'}`}>
      {!active || dir === 'asc' ? '↑' : '↓'}
    </span>
  )
}

function Toast({ visible, message }: { visible: boolean; message: string }) {
  return (
    <div
      className={[
        'fixed bottom-6 right-6 z-50 bg-[#1A202C] text-white text-sm font-medium',
        'px-4 py-3 rounded-xl shadow-lg transition-all duration-300',
        visible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-2 pointer-events-none',
      ].join(' ')}
    >
      {message}
    </div>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

type Tab        = 'stock' | 'scans'
type ScanFilter = 'all' | 'intake' | 'dispatch'

export default function WarehousePage() {
  const [activeTab,      setActiveTab]      = useState<Tab>('stock')
  const [searchQuery,    setSearchQuery]    = useState('')
  const [sortField,      setSortField]      = useState<SortField>('product_name')
  const [sortDir,        setSortDir]        = useState<SortDir>('asc')
  const [scanFilter,     setScanFilter]     = useState<ScanFilter>('all')
  const [toastMsg,       setToastMsg]       = useState('')
  const [toastVisible,   setToastVisible]   = useState(false)

  const showToast = useCallback((msg: string) => {
    setToastMsg(msg)
    setToastVisible(true)
    setTimeout(() => setToastVisible(false), 3000)
  }, [])

  // ── Sort header click ──────────────────────────────────────────────────────
  function handleSort(field: SortField) {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('asc')
    }
  }

  // ── Filtered + sorted warehouse items ─────────────────────────────────────
  const filteredItems = useMemo(() => {
    const q = searchQuery.toLowerCase()
    const base = q
      ? MOCK_WAREHOUSE_ITEMS.filter(
          (i) =>
            i.product_name.toLowerCase().includes(q) ||
            i.brand.toLowerCase().includes(q),
        )
      : MOCK_WAREHOUSE_ITEMS
    return sortItems(base, sortField, sortDir)
  }, [searchQuery, sortField, sortDir])

  // ── Group by category (preserving CATEGORY_ORDER) ─────────────────────────
  const grouped = useMemo(() => {
    const map = new Map<ProductCategory, WarehouseItem[]>()
    for (const cat of CATEGORY_ORDER) map.set(cat, [])
    for (const item of filteredItems) {
      map.get(item.category)?.push(item)
    }
    return [...map.entries()].filter(([, items]) => items.length > 0)
  }, [filteredItems])

  // ── Summary stats ──────────────────────────────────────────────────────────
  const totalItems      = MOCK_WAREHOUSE_ITEMS.length
  const totalBottles    = MOCK_WAREHOUSE_ITEMS.reduce((s, i) => s + i.quantity_in_warehouse, 0)
  const uniqueCategories = new Set(MOCK_WAREHOUSE_ITEMS.map((i) => i.category)).size

  // ── Filtered scans ─────────────────────────────────────────────────────────
  const filteredScans = scanFilter === 'all'
    ? MOCK_WAREHOUSE_SCANS
    : MOCK_WAREHOUSE_SCANS.filter((s) => s.scan_type === scanFilter)

  // ── Sortable column header ─────────────────────────────────────────────────
  function ColHeader({
    field,
    label,
    align = 'text-left',
  }: {
    field: SortField
    label: string
    align?: string
  }) {
    return (
      <th
        className={`px-4 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-[#1A202C] transition-colors ${align}`}
        onClick={() => handleSort(field)}
      >
        {label}
        <SortIcon field={field} active={sortField === field} dir={sortDir} />
      </th>
    )
  }

  return (
    <div className="p-6 max-w-7xl mx-auto">

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-5 flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[#1A202C]">Warehouse Management</h1>
          <p className="text-sm text-[#4A5568] mt-1">Sundance 2026 · {MOCK_WAREHOUSE_ITEMS.length} products tracked</p>
        </div>

        {/* Tab buttons */}
        <div className="flex items-center gap-1 bg-[#F7FAFC] border border-[#E2E8F0] rounded-xl p-1">
          {(['stock', 'scans'] as Tab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={[
                'text-sm font-semibold px-4 py-2 rounded-lg transition-all',
                activeTab === tab
                  ? 'bg-white text-[#1E5A8D] shadow-sm border border-[#E2E8F0]'
                  : 'text-[#4A5568] hover:text-[#1A202C]',
              ].join(' ')}
            >
              {tab === 'stock' ? 'Stock Overview' : 'Scan History'}
            </button>
          ))}
        </div>
      </div>

      {/* ── Tab 1: Stock Overview ────────────────────────────────────────── */}
      {activeTab === 'stock' && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-4 mb-5">
            {[
              { label: 'Total Items',      value: totalItems,         sub: 'distinct products',  color: 'text-[#1A202C]' },
              { label: 'Total Quantity',   value: totalBottles,       sub: 'units in warehouse', color: 'text-[#1E5A8D]' },
              { label: 'Categories',       value: uniqueCategories,   sub: 'product types',      color: 'text-[#6C63FF]' },
            ].map(({ label, value, sub, color }) => (
              <div key={label} className="bg-white border border-[#E2E8F0] rounded-xl px-5 py-4 shadow-sm">
                <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide mb-1">{label}</p>
                <p className={`text-3xl font-bold leading-none ${color}`}>{value}</p>
                <p className="text-xs text-[#4A5568] mt-1">{sub}</p>
              </div>
            ))}
          </div>

          {/* Search bar */}
          <div className="relative mb-4">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#4A5568]"
              fill="none" stroke="currentColor" viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-4.35-4.35M17 11A6 6 0 115 11a6 6 0 0112 0z" />
            </svg>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search by product name or brand…"
              className="w-full max-w-sm pl-9 pr-4 py-2 text-sm border border-[#E2E8F0] rounded-lg bg-white text-[#1A202C] placeholder:text-[#CBD5E0] focus:outline-none focus:ring-2 focus:ring-[#1E5A8D]/20 focus:border-[#1E5A8D] transition"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute left-[15.5rem] top-1/2 -translate-y-1/2 text-[#CBD5E0] hover:text-[#4A5568] transition-colors"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>

          {/* Inventory table (grouped by category) */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-[#F7FAFC] border-b border-[#E2E8F0]">
                    <ColHeader field="product_name"         label="Product Name"          align="text-left"  />
                    <ColHeader field="brand"                label="Brand"                 align="text-left"  />
                    <ColHeader field="category"             label="Category"              align="text-left"  />
                    <ColHeader field="quantity_in_warehouse" label="Qty in Warehouse"     align="text-right" />
                    <ColHeader field="allocated_to_event"   label="Allocated to Event"    align="text-right" />
                    <th className="px-4 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide text-left">Unit</th>
                  </tr>
                </thead>
                <tbody>
                  {grouped.length === 0 ? (
                    <tr>
                      <td colSpan={6} className="px-5 py-10 text-center text-sm text-[#4A5568]">
                        No items match your search.
                      </td>
                    </tr>
                  ) : (
                    grouped.map(([category, items]) => (
                      <>
                        {/* Category group header */}
                        <tr key={`cat-${category}`} className="bg-[#F7FAFC] border-y border-[#E2E8F0]">
                          <td colSpan={6} className="px-4 py-2">
                            <div className="flex items-center gap-2.5">
                              <span className={`text-[11px] font-bold px-2 py-0.5 rounded-full ${CATEGORY_CFG[category]}`}>
                                {category}
                              </span>
                              <span className="text-[10px] text-[#4A5568] font-semibold">
                                {items.length} {items.length === 1 ? 'item' : 'items'}
                              </span>
                            </div>
                          </td>
                        </tr>

                        {/* Product rows */}
                        {items.map((item) => (
                          <tr
                            key={item.id}
                            className="border-b border-[#E2E8F0] last:border-0 hover:bg-[#F7FAFC] transition-colors"
                          >
                            <td className="px-4 py-3 font-semibold text-[#1A202C] whitespace-nowrap pl-8">
                              {item.product_name}
                            </td>
                            <td className="px-4 py-3 text-[#4A5568] whitespace-nowrap">
                              {item.brand}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full ${CATEGORY_CFG[item.category]}`}>
                                {item.category}
                              </span>
                            </td>
                            <td className="px-4 py-3 text-right font-mono font-bold text-[#1A202C]">
                              {item.quantity_in_warehouse}
                            </td>
                            <td className="px-4 py-3 text-right font-mono text-[#4A5568]">
                              {item.allocated_to_event}
                            </td>
                            <td className="px-4 py-3">
                              <span className={`text-[11px] font-semibold px-2 py-0.5 rounded-full capitalize ${UNIT_CFG[item.unit] ?? UNIT_CFG.bottles}`}>
                                {item.unit}
                              </span>
                            </td>
                          </tr>
                        ))}
                      </>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            {/* Table footer */}
            <div className="px-5 py-3 bg-[#F7FAFC] border-t border-[#E2E8F0]">
              <span className="text-xs text-[#4A5568]">
                Showing <span className="font-semibold text-[#1A202C]">{filteredItems.length}</span> of {totalItems} products
              </span>
            </div>
          </div>
        </>
      )}

      {/* ── Tab 2: Scan History ──────────────────────────────────────────── */}
      {activeTab === 'scans' && (
        <>
          {/* Filter pills */}
          <div className="flex items-center gap-2 mb-4">
            {([
              { key: 'all',      label: 'All' },
              { key: 'intake',   label: 'Intake Only' },
              { key: 'dispatch', label: 'Dispatch Only' },
            ] as { key: ScanFilter; label: string }[]).map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setScanFilter(key)}
                className={[
                  'text-xs font-semibold px-3.5 py-1.5 rounded-full border transition-colors',
                  scanFilter === key
                    ? key === 'intake'
                      ? 'bg-green-100 text-[#38A169] border-green-200'
                      : key === 'dispatch'
                      ? 'bg-blue-100 text-[#3498DB] border-blue-200'
                      : 'bg-[#1E5A8D] text-white border-[#1E5A8D]'
                    : 'bg-white text-[#4A5568] border-[#E2E8F0] hover:bg-[#F7FAFC]',
                ].join(' ')}
              >
                {label}
              </button>
            ))}
            <span className="text-xs text-[#4A5568] ml-1">
              {filteredScans.length} scans
            </span>
          </div>

          {/* Scan table */}
          <div className="bg-white border border-[#E2E8F0] rounded-xl overflow-hidden shadow-sm">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-[#F7FAFC] border-b border-[#E2E8F0]">
                    {['Timestamp', 'Barcode', 'Product', 'Scan Type', 'Quantity', 'Destination Bar', 'Scanned By'].map((h) => (
                      <th
                        key={h}
                        className="px-4 py-3 text-[10px] font-bold text-[#4A5568] uppercase tracking-wide text-left whitespace-nowrap"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filteredScans.map((scan) => (
                    <tr
                      key={scan.id}
                      className="border-b border-[#E2E8F0] last:border-0 hover:bg-[#F7FAFC] transition-colors"
                    >
                      <td className="px-4 py-3 font-mono text-xs text-[#4A5568] whitespace-nowrap">
                        {scan.created_at}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-[#718096] whitespace-nowrap">
                        {scan.barcode_raw}
                      </td>
                      <td className="px-4 py-3 font-semibold text-[#1A202C] whitespace-nowrap">
                        {scan.resolved_product_name}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={[
                            'text-[11px] font-bold px-2.5 py-1 rounded-full uppercase',
                            scan.scan_type === 'intake'
                              ? 'bg-green-100 text-[#38A169] border border-green-200'
                              : 'bg-blue-100 text-[#3498DB] border border-blue-200',
                          ].join(' ')}
                        >
                          {scan.scan_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono font-semibold text-[#1A202C]">
                        {scan.quantity}
                      </td>
                      <td className="px-4 py-3 text-[#4A5568] whitespace-nowrap">
                        {scan.destination_bar_id
                          ? BAR_BY_ID[scan.destination_bar_id] ?? `Bar ${scan.destination_bar_id}`
                          : <span className="text-[#CBD5E0]">—</span>
                        }
                      </td>
                      <td className="px-4 py-3 text-[#4A5568] whitespace-nowrap">
                        {scan.scanned_by}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* ── Reconciliation Card ──────────────────────────────────────────── */}
      <div className="mt-6 bg-white border border-[#E2E8F0] rounded-xl shadow-sm overflow-hidden">
        <div className="bg-[#F7FAFC] border-b border-[#E2E8F0] px-5 py-3 flex items-center gap-2">
          <svg className="w-4 h-4 text-[#4A5568]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 11h.01M12 11h.01M15 11h.01M4 19h16a2 2 0 002-2V7a2 2 0 00-2-2H4a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
          <h2 className="text-xs font-bold text-[#4A5568] uppercase tracking-widest">Stock Reconciliation</h2>
        </div>

        <div className="px-5 py-5 flex items-center justify-between flex-wrap gap-6">
          {/* Stat trio */}
          <div className="flex items-stretch gap-6 flex-wrap">
            {[
              { label: 'Expected Stock', value: '250',  color: 'text-[#1A202C]',  sub: 'from event config' },
              { label: 'Actual Stock',   value: '243',  color: 'text-[#1A202C]',  sub: 'from scan logs'   },
              { label: 'Discrepancy',    value: '−7',   color: 'text-[#E53E3E]',  sub: 'units missing',   warning: true },
            ].map(({ label, value, color, sub, warning }) => (
              <div key={label} className="text-center min-w-[110px]">
                <div className="flex items-center justify-center gap-1.5 mb-0.5">
                  {warning && (
                    <svg className="w-3.5 h-3.5 text-[#E53E3E]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
                    </svg>
                  )}
                  <p className={`text-2xl font-bold leading-none ${color}`}>{value}</p>
                </div>
                <p className="text-[10px] font-bold text-[#4A5568] uppercase tracking-wide">{label}</p>
                <p className="text-[10px] text-[#4A5568] mt-0.5">{sub}</p>
              </div>
            ))}
          </div>

          {/* Discrepancy note + action */}
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 rounded-lg px-4 py-3 max-w-xs">
              <svg className="w-4 h-4 text-[#E53E3E] shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
              </svg>
              <p className="text-xs text-[#E53E3E] font-medium leading-snug">
                7-unit shortfall detected. Review scan logs or check for unlogged dispatches.
              </p>
            </div>
            <button
              onClick={() => showToast('Reconciliation report generated')}
              className="text-sm font-semibold text-white bg-[#1E5A8D] hover:bg-[#174a78] px-4 py-2 rounded-lg transition-colors whitespace-nowrap"
            >
              Run Reconciliation
            </button>
          </div>
        </div>
      </div>

      <Toast visible={toastVisible} message={toastMsg} />
    </div>
  )
}
