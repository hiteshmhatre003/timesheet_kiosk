import { useState, useEffect, useCallback } from 'react'
import { getAvailableStock } from '../api.js'

const FILTERS = [
  { label: 'All', warehouse: null },
  { label: 'Rome', warehouse: 'EUR Materials Rome - AE' },
  { label: 'Paris', warehouse: 'EUR Materials Paris - AE' },
  { label: 'India', warehouse: 'EUR Materials India - AE' },
]

export default function StockList() {
  const [filter, setFilter] = useState(FILTERS[0])
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')

  const load = useCallback(async (warehouse) => {
    setLoading(true)
    setError('')
    try {
      const data = await getAvailableStock(warehouse)
      setItems(data || [])
    } catch (err) {
      setError(err.message || 'Could not load stock')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load(filter.warehouse)
  }, [filter, load])

  const visibleItems = items.filter((it) => {
    if (!query.trim()) return true
    const q = query.toLowerCase()
    return (it.item_name || '').toLowerCase().includes(q) || (it.item_code || '').toLowerCase().includes(q)
  })

  return (
    <div className="screen">
      <h2>Available Stock</h2>

      <div className="chip-row">
        {FILTERS.map((f) => (
          <button
            key={f.label}
            type="button"
            className={`chip ${filter.label === f.label ? 'chip-active' : ''}`}
            onClick={() => setFilter(f)}
          >
            {f.label}
          </button>
        ))}
      </div>

      <input
        type="text"
        className="search-box"
        placeholder="Search stock"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      <button type="button" className="link-btn refresh-btn" onClick={() => load(filter.warehouse)}>
        Refresh
      </button>

      {loading && <div className="hint">Loading…</div>}
      {error && <div className="error-banner">{error}</div>}
      {!loading && !error && visibleItems.length === 0 && <div className="hint">No stock found.</div>}

      <div className="stock-grid">
        {visibleItems.map((it) => (
          <div className="stock-card" key={`${it.item_code}-${it.warehouse}`}>
            <div className="stock-photo">
              {it.image ? <img src={it.image} alt={it.item_name} /> : <span>No photo</span>}
            </div>
            <div className="stock-info">
              <strong>{it.item_name || it.item_code}</strong>
              <span>
                {it.qty} {it.uom}
              </span>
              <span className="stock-warehouse">{it.warehouse}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
