/**
 * Workload Analysis API client.
 *
 * Base URL resolution (in order of preference):
 *   1. `VITE_WORKLOAD_API_BASE` from `.env.development` / `.env.production`.
 *   2. Dev builds (`import.meta.env.DEV`) -> local Flask shim at
 *      `http://localhost:5003/api` (see `backend_workload/app.py`).
 *   3. Production builds -> the deployed HTTP API Gateway URL below.
 *
 * The production fallback is intentional: when somebody forgets to create
 * `Frontend/.env.production` (which is gitignored), `npm run build` would
 * otherwise inline the localhost URL and the deployed site reports
 * "Backend offline" with `ERR_CONNECTION_REFUSED` from the browser. The
 * fallback keeps the app working out of the box; override via env when
 * pointing at a staging API.
 *
 * Authentication
 * --------------
 * The deployed API is JWT-protected via `safexpressops-jwt-authorizer`. We
 * read the same access token the rest of the app uses (set during the
 * Django login flow under localStorage key `ACCESS_TOKEN` -> 'access',
 * see `Frontend/src/token.js`) and attach `Authorization: Bearer <token>`
 * to every workload API request — including the multipart PDF upload.
 *
 * The local Flask dev shim is not JWT-protected, so the header is harmless
 * there. The /api/health route in production is also public so the
 * frontend can probe connectivity without a token.
 */

import { ACCESS_TOKEN } from '../token.js';

const PROD_WORKLOAD_API_BASE =
  'https://jwf4gfdzyd.execute-api.ap-southeast-1.amazonaws.com/api';
const DEV_WORKLOAD_API_BASE = 'http://localhost:5003/api';

export const WORKLOAD_API_BASE =
  import.meta.env.VITE_WORKLOAD_API_BASE
  || (import.meta.env.DEV ? DEV_WORKLOAD_API_BASE : PROD_WORKLOAD_API_BASE);

// Surface the URL in the console so debugging "Backend offline" is one
// glance away. Logged once at module load — cheap and silent in tests.
if (typeof console !== 'undefined' && console.info) {
  console.info(`[workloadAPI] base URL: ${WORKLOAD_API_BASE}`);
}

/** Attach Authorization: Bearer <token> if we have one. Never throws. */
const _withAuthHeaders = (existing = {}) => {
  const token = localStorage.getItem(ACCESS_TOKEN);
  if (!token) return existing;
  return { ...existing, Authorization: `Bearer ${token}` };
};

// Helper: parses {success, data, message} envelopes and surfaces backend
// error messages to the caller.
const _request = async (path, options = {}) => {
  const res = await fetch(`${WORKLOAD_API_BASE}${path}`, {
    ...options,
    headers: _withAuthHeaders(options.headers),
  });
  let body = null;
  try {
    body = await res.json();
  } catch (_) {
    body = { success: false, message: `Unexpected response (HTTP ${res.status})` };
  }
  if (!res.ok || body?.success === false) {
    const err = new Error(body?.message || `HTTP ${res.status}`);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
};

// ---------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------

export const checkAPIHealth = async () => {
  try {
    const body = await _request('/health');
    return body.success === true;
  } catch (_e) {
    return false;
  }
};

// ---------------------------------------------------------------------
// Time configuration (8 rates: per-pallet + per-piece for the 4 phases)
// ---------------------------------------------------------------------

export const workloadConfigAPI = {
  async getConfig() {
    const body = await _request('/config');
    return body.data;
  },

  /** Save the caller's PERSONAL rate-config row. Other users are not affected. */
  async updateConfig(config) {
    const body = await _request('/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    return body.data;
  },

  /** Drop the caller's personal row so they go back to the organization default. */
  async resetToDefault() {
    const body = await _request('/config', { method: 'DELETE' });
    return body.data;
  },
};

// ---------------------------------------------------------------------
// UOM dropdown values
// ---------------------------------------------------------------------

export const workloadUomAPI = {
  async listUoms() {
    const body = await _request('/uom');
    return body.data;
  },

  async addUom(uom) {
    const body = await _request('/uom', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ uom }),
    });
    return body.data;
  },

  async deleteUom(uom) {
    const body = await _request(`/uom/${encodeURIComponent(uom)}`, {
      method: 'DELETE',
    });
    return body.data;
  },
};

// ---------------------------------------------------------------------
// Workload calculation history
// ---------------------------------------------------------------------

export const workloadCalculationAPI = {
  async calculate(payload) {
    const body = await _request('/workload/calculate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return body.data;
  },

  async getHistory({ mode = null, limit = 50, offset = 0 } = {}) {
    const qs = new URLSearchParams();
    if (mode) qs.set('mode', mode);
    qs.set('limit', String(limit));
    qs.set('offset', String(offset));
    const body = await _request(`/workload/history?${qs.toString()}`);
    return body;
  },

  async getCalculationById(id) {
    const body = await _request(`/workload/history/${encodeURIComponent(id)}`);
    return body.data;
  },

  async deleteCalculation(id) {
    const body = await _request(`/workload/history/${encodeURIComponent(id)}`, {
      method: 'DELETE',
    });
    return body;
  },
};

// ---------------------------------------------------------------------
// PDF auto-fill
// ---------------------------------------------------------------------

export const workloadPdfAPI = {
  /**
   * Parse a single PMRL-style PDF. Returns the items + palletId or throws.
   * `file` is a File / Blob from a <input type="file" /> change event.
   */
  async parsePdf(file) {
    const form = new FormData();
    form.append('file', file, file?.name || 'upload.pdf');
    const res = await fetch(`${WORKLOAD_API_BASE}/workload/pdf-parse`, {
      method: 'POST',
      // No Content-Type — let the browser set the multipart boundary for us.
      // Auth header is added separately so we don't clobber the boundary.
      headers: _withAuthHeaders({}),
      body: form,
    });
    let body = null;
    try {
      body = await res.json();
    } catch (_) {
      body = { success: false, message: `Unexpected response (HTTP ${res.status})` };
    }
    if (!res.ok || body?.success === false) {
      const err = new Error(body?.message || `HTTP ${res.status}`);
      err.status = res.status;
      err.body = body;
      throw err;
    }
    return body; // { success, palletId, items, pages, warnings, rawText }
  },
};
