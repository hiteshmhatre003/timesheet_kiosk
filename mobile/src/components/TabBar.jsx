export default function TabBar({ active, onChange }) {
  return (
    <nav className="tab-bar">
      <button
        type="button"
        className={`tab-btn ${active === 'purchase' ? 'active' : ''}`}
        onClick={() => onChange('purchase')}
      >
        <span className="tab-icon">＋</span>
        New Purchase
      </button>
      <button
        type="button"
        className={`tab-btn ${active === 'stock' ? 'active' : ''}`}
        onClick={() => onChange('stock')}
      >
        <span className="tab-icon">▤</span>
        Stock
      </button>
    </nav>
  )
}
