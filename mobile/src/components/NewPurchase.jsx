import { useState, useRef, useEffect } from 'react'
import { searchItems, getItemUoms, createPurchaseEntry } from '../api.js'

const REGIONS = ['Rome', 'Paris', 'India']

function emptyForm() {
  return {
    region: '',
    item_code: '',
    item_name: '',
    qty: '',
    uom: '',
    supplier: '',
    rate: '',
    posting_date: new Date().toISOString().slice(0, 10),
    remarks: '',
  }
}

// Camera photos can be several MB - resize/compress client-side before
// upload so this stays fast on shop-floor wifi/mobile data.
async function compressImage(file, maxDim = 1280, quality = 0.75) {
  const img = document.createElement('img')
  const url = URL.createObjectURL(file)
  try {
    await new Promise((resolve, reject) => {
      img.onload = resolve
      img.onerror = reject
      img.src = url
    })
  } finally {
    URL.revokeObjectURL(url)
  }

  let { width, height } = img
  if (width > maxDim || height > maxDim) {
    const scale = maxDim / Math.max(width, height)
    width = Math.round(width * scale)
    height = Math.round(height * scale)
  }

  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  canvas.getContext('2d').drawImage(img, 0, 0, width, height)

  const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality))
  return new File([blob], 'item.jpg', { type: 'image/jpeg' })
}

export default function NewPurchase() {
  const [form, setForm] = useState(emptyForm())
  const [itemQuery, setItemQuery] = useState('')
  const [itemResults, setItemResults] = useState([])
  const [showResults, setShowResults] = useState(false)
  const [uomOptions, setUomOptions] = useState([])
  const [imageFile, setImageFile] = useState(null)
  const [imagePreview, setImagePreview] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [successMsg, setSuccessMsg] = useState('')
  const [recent, setRecent] = useState([])
  const searchTimer = useRef(null)

  useEffect(() => {
    if (searchTimer.current) clearTimeout(searchTimer.current)
    if (!itemQuery.trim()) {
      setItemResults([])
      return undefined
    }
    searchTimer.current = setTimeout(async () => {
      try {
        const results = await searchItems(itemQuery.trim())
        setItemResults(results || [])
      } catch {
        setItemResults([])
      }
    }, 300)
    return () => clearTimeout(searchTimer.current)
  }, [itemQuery])

  function selectRegion(region) {
    setForm((f) => ({ ...f, region }))
  }

  async function selectItem(item) {
    setForm((f) => ({ ...f, item_code: item.item_code, item_name: item.item_name, uom: item.stock_uom }))
    setItemQuery(item.item_name)
    setShowResults(false)
    try {
      const details = await getItemUoms(item.item_code)
      setUomOptions(details.uoms && details.uoms.length ? details.uoms : [item.stock_uom])
    } catch {
      setUomOptions([item.stock_uom])
    }
  }

  async function handleImagePick(e) {
    const file = e.target.files && e.target.files[0]
    if (!file) return
    try {
      const compressed = await compressImage(file)
      setImageFile(compressed)
      setImagePreview(URL.createObjectURL(compressed))
    } catch {
      setImageFile(file)
      setImagePreview(URL.createObjectURL(file))
    }
  }

  function resetForm() {
    setForm(emptyForm())
    setItemQuery('')
    setItemResults([])
    setUomOptions([])
    setImageFile(null)
    setImagePreview(null)
  }

  function isValid() {
    return Boolean(
      form.region && form.item_code && Number(form.qty) > 0 && form.uom && form.posting_date && imageFile
    )
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setSuccessMsg('')
    if (!isValid()) {
      setError('Fill in region, item, quantity, UOM and a photo before submitting.')
      return
    }
    setSubmitting(true)
    try {
      const result = await createPurchaseEntry(
        {
          region: form.region,
          item_code: form.item_code,
          qty: form.qty,
          uom: form.uom,
          supplier: form.supplier,
          rate: form.rate,
          posting_date: form.posting_date,
          remarks: form.remarks,
        },
        imageFile
      )
      setSuccessMsg(`Saved ${result.name} — stock updated in ${form.region}.`)
      setRecent((r) =>
        [{ name: result.name, item_name: form.item_name, qty: form.qty, uom: form.uom }, ...r].slice(0, 5)
      )
      resetForm()
    } catch (err) {
      setError(err.message || 'Could not save purchase entry')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="screen">
      <h2>New Purchase</h2>

      <form onSubmit={handleSubmit} className="purchase-form">
        <div className="field">
          <label>Region</label>
          <div className="chip-row">
            {REGIONS.map((r) => (
              <button
                type="button"
                key={r}
                className={`chip ${form.region === r ? 'chip-active' : ''}`}
                onClick={() => selectRegion(r)}
              >
                {r}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label>Item</label>
          <input
            type="text"
            placeholder="Search item name or code"
            value={itemQuery}
            onChange={(e) => {
              setItemQuery(e.target.value)
              setShowResults(true)
              setForm((f) => ({ ...f, item_code: '', item_name: '' }))
            }}
            onFocus={() => setShowResults(true)}
          />
          {showResults && itemResults.length > 0 && (
            <ul className="result-list">
              {itemResults.map((it) => (
                <li key={it.item_code} onClick={() => selectItem(it)}>
                  <span className="result-name">{it.item_name}</span>
                  <span className="result-code">{it.item_code}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="field-row">
          <div className="field">
            <label>Quantity</label>
            <input
              type="number"
              inputMode="decimal"
              min="0"
              step="any"
              value={form.qty}
              onChange={(e) => setForm((f) => ({ ...f, qty: e.target.value }))}
              required
            />
          </div>
          <div className="field">
            <label>UOM</label>
            <select
              value={form.uom}
              onChange={(e) => setForm((f) => ({ ...f, uom: e.target.value }))}
              disabled={!uomOptions.length}
            >
              {uomOptions.length === 0 && <option value="">—</option>}
              {uomOptions.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="field">
          <label>Supplier</label>
          <input
            type="text"
            value={form.supplier}
            onChange={(e) => setForm((f) => ({ ...f, supplier: e.target.value }))}
          />
        </div>

        <div className="field-row">
          <div className="field">
            <label>Rate</label>
            <input
              type="number"
              inputMode="decimal"
              min="0"
              step="any"
              value={form.rate}
              onChange={(e) => setForm((f) => ({ ...f, rate: e.target.value }))}
            />
          </div>
          <div className="field">
            <label>Date</label>
            <input
              type="date"
              value={form.posting_date}
              onChange={(e) => setForm((f) => ({ ...f, posting_date: e.target.value }))}
              required
            />
          </div>
        </div>

        <div className="field">
          <label>Photo</label>
          <label className="photo-picker">
            {imagePreview ? (
              <img src={imagePreview} alt="Item" className="photo-preview" />
            ) : (
              <span className="photo-placeholder">Tap to take a photo</span>
            )}
            <input type="file" accept="image/*" capture="environment" onChange={handleImagePick} hidden />
          </label>
        </div>

        <div className="field">
          <label>Remarks (optional)</label>
          <input
            type="text"
            value={form.remarks}
            onChange={(e) => setForm((f) => ({ ...f, remarks: e.target.value }))}
          />
        </div>

        {error && <div className="error-banner">{error}</div>}
        {successMsg && <div className="success-banner">{successMsg}</div>}

        <button type="submit" className="primary-btn" disabled={submitting || !isValid()}>
          {submitting ? 'Saving…' : 'Save Purchase'}
        </button>
      </form>

      {recent.length > 0 && (
        <div className="recent-list">
          <h3>Added this session</h3>
          {recent.map((r) => (
            <div className="recent-item" key={r.name}>
              <span>{r.item_name}</span>
              <span>
                {r.qty} {r.uom}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
