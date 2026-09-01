// Bridge layer between this React app and Frappe.
//
// Deployment assumption: this app is served BY the same Frappe site
// (e.g. https://uatamal.frappe.cloud/purchase-app), so plain relative
// paths like "/api/..." resolve correctly and the session cookie set by
// /api/method/login is automatically sent with every later request.
//
// Frappe requires an X-Frappe-CSRF-Token header on state-changing
// (non-GET) requests once you're in a cookie session. We fetch a fresh
// token via purchase_mobile.api.get_csrf_token right after login and keep it in
// memory for the rest of the session.

let csrfToken = null

async function request(path, { method = 'GET', body, isForm = false } = {}) {
  const headers = {}
  if (csrfToken && method !== 'GET') {
    headers['X-Frappe-CSRF-Token'] = csrfToken
  }
  if (body && !isForm) {
    headers['Content-Type'] = 'application/json'
  }

  const res = await fetch(path, {
    method,
    credentials: 'include',
    headers,
    body: isForm ? body : body ? JSON.stringify(body) : undefined,
  })

  const contentType = res.headers.get('content-type') || ''
  const data = contentType.includes('application/json') ? await res.json() : await res.text()

  if (!res.ok) {
    throw new Error(extractErrorMessage(data))
  }
  return data && typeof data === 'object' && 'message' in data ? data.message : data
}

function extractErrorMessage(data) {
  if (typeof data === 'string') return data || 'Request failed'
  if (data && data._server_messages) {
    try {
      const outer = JSON.parse(data._server_messages)
      const first = JSON.parse(outer[0])
      if (first.message) return first.message
    } catch {
      // fall through to other fields
    }
  }
  if (data && data.exception) return data.exception
  if (data && data.message) return data.message
  return 'Request failed'
}

export async function login(usr, pwd) {
  await request('/api/method/login', {
    method: 'POST',
    isForm: true,
    body: new URLSearchParams({ usr, pwd }),
  })
  csrfToken = await request('/api/method/purchase_mobile.api.get_csrf_token')
}

export async function logout() {
  try {
    await request('/api/method/logout', { method: 'POST' })
  } finally {
    csrfToken = null
  }
}

// Called on app startup - if the browser still has a valid session
// cookie from a previous visit, this quietly restores the session
// without asking the user to log in again.
export async function checkSession() {
  try {
    csrfToken = await request('/api/method/purchase_mobile.api.get_csrf_token')
    return true
  } catch {
    csrfToken = null
    return false
  }
}

export function searchItems(txt) {
  return request(`/api/method/purchase_mobile.api.search_items?txt=${encodeURIComponent(txt)}`)
}

export function getItemUoms(itemCode) {
  return request(`/api/method/purchase_mobile.api.get_item_uoms?item_code=${encodeURIComponent(itemCode)}`)
}

export function getAvailableStock(warehouse) {
  const qs = warehouse ? `?warehouse=${encodeURIComponent(warehouse)}` : ''
  return request(`/api/method/purchase_mobile.api.get_available_stock${qs}`)
}

export function createPurchaseEntry(fields, imageFile) {
  const form = new FormData()
  Object.entries(fields).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      form.append(key, value)
    }
  })
  if (imageFile) {
    form.append('item_image', imageFile)
  }
  return request('/api/method/purchase_mobile.api.create_purchase_entry', {
    method: 'POST',
    isForm: true,
    body: form,
  })
}
