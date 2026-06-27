/**
 * SleshShopPicker — searchable dropdown of Slesh shops with offline
 * fallback. Used by Wizard Step 3 (Bars editor) to link each XProject
 * bar row to a Slesh shop_id.
 *
 * Behaviors:
 *   - Loads /events/slesh-shops on mount (cached for 4min FE-side,
 *     5min BE-side, so rapid wizard nav doesn't hit Slesh repeatedly)
 *   - Filters shops by substring match on name as Omar types
 *   - excelHint prop: when set (e.g. "MAIN BAR"), the closest matching
 *     shop is marked with a ✓ and shown first as a suggestion. Hint
 *     matching is lowercase substring — generous, but the picker stays
 *     authoritative; this is a cue, not a hard match.
 *   - Offline mode: when backend returns source="offline" (Slesh down,
 *     misconfigured brand_id, network error), the picker hides the
 *     dropdown and shows a plain text input so Omar can paste a
 *     shop_id directly. Sundance still ships either way.
 *   - Keyboard nav: ↑/↓ to move highlight, Enter to select, Esc to close
 *   - Read-out below: source + count + cache age so we can debug field
 *     issues without F12
 *
 * Defensive choices:
 *   - Never throws — query errors fall through to offline mode
 *   - Empty shops list is fine — picker just shows "No shops" + manual
 *     fallback link
 *   - Click outside closes the dropdown; we use a document mousedown
 *     listener (matches existing dropdown patterns in chat module)
 */
import { useEffect, useMemo, useRef, useState } from "react"

import { useSleshShops } from "@/features/events/hooks"
import type { SleshShop } from "@/lib/eventPlan"

interface Props {
  value: string | null
  onChange: (id: string | null) => void
  /** Free-text hint from the parsed Excel (e.g. "MAIN BAR"). Picker
   *  uses it to highlight a suggested match. Not a hard filter. */
  excelHint?: string | null
  /** Optional placeholder for the search input. */
  placeholder?: string
}

const inputCls =
  "w-full rounded-lg border border-[#E2E8F0] px-3 py-2 text-sm text-[#1A202C] focus:outline-none focus:ring-2 focus:ring-[#3182CE]/30 focus:border-[#3182CE]"

export function SleshShopPicker({ value, onChange, excelHint, placeholder }: Props) {
  const query = useSleshShops()
  const [searchText, setSearchText] = useState("")
  const [isOpen, setIsOpen] = useState(false)
  const [highlightIdx, setHighlightIdx] = useState(0)
  const rootRef = useRef<HTMLDivElement | null>(null)

  // ── Derive runtime mode ──────────────────────────────────────────
  const isLoading = query.isPending
  const isOffline = !isLoading && (query.isError || query.data?.source === "offline")
  const shops: SleshShop[] = query.data?.shops ?? []
  const source = query.data?.source ?? (query.isError ? "offline" : "live")

  // ── Suggested match from excelHint ───────────────────────────────
  // Lowercase substring match. Bidirectional: either the hint contains
  // the shop name or vice versa. Picks the first match in the list.
  const suggestedShopId = useMemo<string | null>(() => {
    if (!excelHint) return null
    const h = excelHint.trim().toLowerCase()
    if (!h) return null
    const hit = shops.find((s) => {
      const n = s.name.trim().toLowerCase()
      return n === h || n.includes(h) || h.includes(n)
    })
    return hit?.id ?? null
  }, [excelHint, shops])

  // ── Selected shop (for display) ──────────────────────────────────
  const selectedShop = useMemo(
    () => (value ? shops.find((s) => s.id === value) ?? null : null),
    [value, shops],
  )

  // ── Filter shops by search text. Suggested match floats to top. ──
  const filteredShops = useMemo(() => {
    const q = searchText.trim().toLowerCase()
    let list = shops
    if (q) {
      list = shops.filter((s) => s.name.toLowerCase().includes(q))
    }
    if (suggestedShopId) {
      const idx = list.findIndex((s) => s.id === suggestedShopId)
      if (idx > 0) {
        list = [list[idx], ...list.slice(0, idx), ...list.slice(idx + 1)]
      }
    }
    return list
  }, [shops, searchText, suggestedShopId])

  // ── Reset highlight when filtered list changes ───────────────────
  useEffect(() => {
    setHighlightIdx(0)
  }, [searchText, filteredShops.length])

  // ── Outside-click closes dropdown ────────────────────────────────
  useEffect(() => {
    if (!isOpen) return
    function onMouseDown(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener("mousedown", onMouseDown)
    return () => document.removeEventListener("mousedown", onMouseDown)
  }, [isOpen])

  // ── Key handlers ─────────────────────────────────────────────────
  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault()
      setIsOpen(true)
      setHighlightIdx((i) => Math.min(i + 1, Math.max(0, filteredShops.length - 1)))
    } else if (e.key === "ArrowUp") {
      e.preventDefault()
      setHighlightIdx((i) => Math.max(i - 1, 0))
    } else if (e.key === "Enter") {
      e.preventDefault()
      const pick = filteredShops[highlightIdx]
      if (pick) {
        onChange(pick.id)
        setSearchText("")
        setIsOpen(false)
      }
    } else if (e.key === "Escape") {
      setIsOpen(false)
      setSearchText("")
    }
  }

  // ── Offline path: manual shop_id text field ──────────────────────
  if (isOffline) {
    return (
      <div className="space-y-1.5">
        <div className="flex items-center gap-2 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 6a1 1 0 011 1v3a1 1 0 11-2 0V7a1 1 0 011-1zm0 8a1 1 0 100-2 1 1 0 000 2z" clipRule="evenodd" />
          </svg>
          Slesh API unreachable. Type the shop_id manually for now.
        </div>
        <input
          className={inputCls}
          placeholder="Paste Slesh shop_id (24-char hex)"
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value || null)}
        />
        <button
          onClick={() => query.refetch()}
          className="text-xs text-[#3182CE] hover:underline"
        >
          Try again
        </button>
      </div>
    )
  }

  // ── Display string: selected shop name, or empty ─────────────────
  const displayValue = isOpen ? searchText : selectedShop?.name ?? ""

  return (
    <div ref={rootRef} className="relative">
      <input
        className={inputCls}
        placeholder={placeholder ?? (isLoading ? "Loading shops…" : "Search shops…")}
        value={displayValue}
        onFocus={() => {
          setIsOpen(true)
          setSearchText("")
        }}
        onChange={(e) => {
          setSearchText(e.target.value)
          setIsOpen(true)
        }}
        onKeyDown={handleKeyDown}
        disabled={isLoading}
      />

      {/* Clear button when a value is selected */}
      {value && !isOpen && (
        <button
          onClick={() => onChange(null)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-[#A0AEC0] hover:text-[#E53E3E] text-sm"
          aria-label="Clear shop selection"
        >
          ×
        </button>
      )}

      {/* Dropdown */}
      {isOpen && !isLoading && (
        <div className="absolute z-10 mt-1 w-full max-h-64 overflow-y-auto bg-white border border-[#E2E8F0] rounded-lg shadow-lg">
          {filteredShops.length === 0 ? (
            <div className="px-3 py-2 text-sm text-[#A0AEC0]">
              No shops match "{searchText}".
            </div>
          ) : (
            filteredShops.map((shop, idx) => {
              const isSelected = shop.id === value
              const isHighlighted = idx === highlightIdx
              const isSuggested = shop.id === suggestedShopId
              return (
                <button
                  key={shop.id}
                  onMouseDown={(e) => e.preventDefault()}  // keep input focus
                  onClick={() => {
                    onChange(shop.id)
                    setSearchText("")
                    setIsOpen(false)
                  }}
                  onMouseEnter={() => setHighlightIdx(idx)}
                  className={[
                    "w-full text-left px-3 py-2 text-sm flex items-center gap-2 transition-colors",
                    isHighlighted ? "bg-[#F0F4F8]" : "",
                    isSelected ? "font-semibold text-[#1E5A8D]" : "text-[#1A202C]",
                  ].join(" ")}
                >
                  {isSuggested && (
                    <span className="text-[#1ABC9C] text-xs font-semibold" title="Suggested match from Excel">✓</span>
                  )}
                  <span className="flex-1 truncate">{shop.name}</span>
                  {!shop.is_active && (
                    <span className="text-[10px] text-[#A0AEC0]">inactive</span>
                  )}
                </button>
              )
            })
          )}
        </div>
      )}

      {/* Debug read-out: source + count + cache age */}
      {!isLoading && query.data && (
        <div className="mt-1 text-[10px] text-[#A0AEC0]">
          {source} · {shops.length} shop{shops.length === 1 ? "" : "s"}
          {query.data.cache_ttl_s > 0 && ` · cache ${Math.round(query.data.cache_ttl_s / 60)}m`}
        </div>
      )}
    </div>
  )
}
