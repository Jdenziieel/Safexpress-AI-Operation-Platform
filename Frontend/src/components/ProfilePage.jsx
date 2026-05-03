import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  User, Mail, Calendar, Shield,
  Activity, RefreshCw, AlertCircle, TrendingUp,
  Clock, BarChart3
} from 'lucide-react';
import '../css/ProfilePage.css';
import { quotaApi } from '../api';

// ─────────────────────────────────────────────────────────────────────────────
// Formatters (shared)
// ─────────────────────────────────────────────────────────────────────────────

const formatTokens = (num) => {
  if (num === null || num === undefined || Number.isNaN(num)) return '0';
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(2)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(1)}K`;
  return num.toLocaleString();
};

const formatCost = (n) => {
  const v = Number(n) || 0;
  if (v === 0) return '$0.00';
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
};

const formatTimestamp = (ts) => {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit'
    });
  } catch { return ts; }
};

const getDaysUntilReset = (resetDate) => {
  if (!resetDate) return null;
  const reset = new Date(resetDate);
  const now = new Date();
  return Math.ceil((reset - now) / 86_400_000);
};

const getStatusTone = (pct) => {
  if (pct >= 90) return 'critical';
  if (pct >= 75) return 'warning';
  return 'healthy';
};

// Friendly labels for the operation column. Anything not listed is
// rendered raw — keeps unknown future operations debuggable.
const OPERATION_LABELS = {
  chat: 'Chat',
  chat_stream: 'SFXbot Chat',
  classify: 'Classification',
  classification: 'Classification',
  pdf_parse: 'PDF processing',
  parse: 'PDF processing',
  enhance: 'Query enhancement',
  rerank: 'Rerank',
  title: 'Title generation',
  search_embed: 'Embedding lookup',
  auto_reset: 'Period reset',
  admin_reset: 'Admin manual reset',
  period_reset: 'Period reset',
};

const SERVICE_LABELS = {
  'knowledge-base': 'Knowledge Base',
  knowledge_base: 'Knowledge Base',
  system: 'Period Resets',
};

// True for any audit-only "service": today that's just the auto-reset /
// admin-reset snapshots written by the quota lambdas with service='system'.
// Centralised as a function so adding new audit-only services later
// (e.g. 'billing_adjustment') is a one-line change.
const isResetService = (svc) => (svc || '').toLowerCase() === 'system';
const isResetOperation = (op) =>
  ['auto_reset', 'admin_reset', 'period_reset'].includes((op || '').toLowerCase());

// ─────────────────────────────────────────────────────────────────────────────
// Daily/weekly/monthly bucketing helpers
//
// The backend hands us ONE row per UTC day (zero-filled) regardless of
// window. That's perfect for a 7- or 30-day view, but at 90/180/365 days
// the bars get visually unreadable and the viewer just sees noise. So
// we re-bucket client-side once we know the window length.
//
// Bucketing rule of thumb (chosen so each grouping yields ~10–14 bars,
// which fits the chart container without overlap or wide gaps):
//   ≤ 30d  → daily      (1 day per bar)
//   ≤ 90d  → weekly     (7 days per bar)
//   ≤ 180d → biweekly   (14 days per bar)
//   else   → monthly    (1 calendar month per bar)
// ─────────────────────────────────────────────────────────────────────────────

const CHART_GRAIN = {
  DAILY: 'daily',
  WEEKLY: 'weekly',
  BIWEEKLY: 'biweekly',
  MONTHLY: 'monthly',
};

const grainForWindow = (windowDays) => {
  if (windowDays <= 30) return CHART_GRAIN.DAILY;
  if (windowDays <= 90) return CHART_GRAIN.WEEKLY;
  if (windowDays <= 180) return CHART_GRAIN.BIWEEKLY;
  return CHART_GRAIN.MONTHLY;
};

const grainLabel = (grain) => ({
  [CHART_GRAIN.DAILY]: 'Daily',
  [CHART_GRAIN.WEEKLY]: 'Weekly',
  [CHART_GRAIN.BIWEEKLY]: 'Bi-weekly',
  [CHART_GRAIN.MONTHLY]: 'Monthly',
}[grain] || 'Daily');

// Format a YYYY-MM-DD bucket key into a short human label appropriate
// for each grain. Daily/weekly/biweekly want "MMM D"; monthly wants
// "MMM YYYY" so the year context isn't lost over a 365-day window.
const formatBucketLabel = (key, grain) => {
  if (!key) return '';
  try {
    if (grain === CHART_GRAIN.MONTHLY) {
      const d = new Date(key + '-01T00:00:00Z'); // key is YYYY-MM
      return d.toLocaleDateString('en-US', { month: 'short', year: 'numeric' });
    }
    const d = new Date(key + 'T00:00:00Z'); // key is YYYY-MM-DD
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  } catch {
    return key;
  }
};

// Re-bucket the daily array. `days` is the backend's by_day list of
// `{date: 'YYYY-MM-DD', total_tokens, cost_usd, calls}` objects.
// Returns `{key, label, total_tokens, cost_usd, calls}` for each bucket.
const bucketByGrain = (days, grain) => {
  if (!days || days.length === 0) return [];
  if (grain === CHART_GRAIN.DAILY) {
    return days.map(d => ({
      key: d.date,
      label: formatBucketLabel(d.date, CHART_GRAIN.DAILY),
      total_tokens: d.total_tokens || 0,
      cost_usd: d.cost_usd || 0,
      calls: d.calls || 0,
    }));
  }

  const stride = grain === CHART_GRAIN.WEEKLY ? 7 : grain === CHART_GRAIN.BIWEEKLY ? 14 : null;

  if (stride) {
    // Walk the sorted day list, grouping every `stride` consecutive
    // days into a single bucket. Bucket key = the FIRST day of the
    // bucket (so the x-axis label reads naturally as a "week of …").
    const buckets = [];
    for (let i = 0; i < days.length; i += stride) {
      const slice = days.slice(i, i + stride);
      const startKey = slice[0].date;
      buckets.push({
        key: startKey,
        label: formatBucketLabel(startKey, CHART_GRAIN.WEEKLY),
        total_tokens: slice.reduce((acc, d) => acc + (d.total_tokens || 0), 0),
        cost_usd:    slice.reduce((acc, d) => acc + (d.cost_usd     || 0), 0),
        calls:       slice.reduce((acc, d) => acc + (d.calls        || 0), 0),
      });
    }
    return buckets;
  }

  // Monthly grain: bucket by the YYYY-MM prefix of each day's date.
  // Using a Map preserves insertion order so the output stays sorted.
  const byMonth = new Map();
  days.forEach(d => {
    const month = (d.date || '').slice(0, 7); // 'YYYY-MM'
    if (!month) return;
    const cur = byMonth.get(month) || {
      key: month,
      label: formatBucketLabel(month, CHART_GRAIN.MONTHLY),
      total_tokens: 0,
      cost_usd: 0,
      calls: 0,
    };
    cur.total_tokens += d.total_tokens || 0;
    cur.cost_usd    += d.cost_usd     || 0;
    cur.calls       += d.calls        || 0;
    byMonth.set(month, cur);
  });
  return Array.from(byMonth.values());
};

// ─────────────────────────────────────────────────────────────────────────────
// Monthly history (Fix B)
//
// Builds a per-calendar-month view of consumption that the user can
// trust as "what I actually spent that month". For each PRIOR month we
// look at the auto_reset / admin_reset snapshot row written when the
// month rolled over — its `total_tokens` IS the period total. For the
// CURRENT month we use the live `summary.current_usage`. This gives us
// a clean monthly grouped chart even when the user has years of
// history (capped at the user's selected window).
// ─────────────────────────────────────────────────────────────────────────────

const buildMonthlyHistory = (logs, summary) => {
  const months = new Map(); // 'YYYY-MM' -> { tokens, cost, source }

  // 1) Past months from reset snapshots. These are authoritative —
  //    the value at reset time is exactly what the user consumed
  //    during the period that ended.
  (logs || []).forEach(row => {
    if (!isResetOperation(row.operation)) return;
    const ts = row.timestamp;
    if (!ts || ts.length < 7) return;
    // The reset row is written AT the rollover (e.g. May 1 00:05 UTC)
    // for the period that just ended (April). So the bucket month is
    // the month BEFORE the reset's month.
    const resetDate = new Date(ts);
    const periodEnd = new Date(Date.UTC(
      resetDate.getUTCFullYear(),
      resetDate.getUTCMonth() - 1,
      1
    ));
    const key = `${periodEnd.getUTCFullYear()}-${String(periodEnd.getUTCMonth() + 1).padStart(2, '0')}`;
    months.set(key, {
      key,
      label: formatBucketLabel(key, CHART_GRAIN.MONTHLY),
      total_tokens: row.total_tokens || 0,
      cost_usd:     row.cost_usd     || 0,
      source: 'reset',
    });
  });

  // 2) Current month from the live summary. Use the calendar month of
  //    "now" so a fresh user with no resets still sees their current
  //    consumption represented.
  if (summary) {
    const now = new Date();
    const curKey = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`;
    months.set(curKey, {
      key: curKey,
      label: formatBucketLabel(curKey, CHART_GRAIN.MONTHLY),
      total_tokens: summary.current_usage || 0,
      cost_usd:     summary.current_cost_usd || 0,
      source: 'live',
    });
  }

  return Array.from(months.values()).sort((a, b) => a.key.localeCompare(b.key));
};

// ─────────────────────────────────────────────────────────────────────────────
// Activity grouping (chat_stream + search_embed → "SFXbot Chat")
//
// One chat turn produces TWO rows (visible answer + hidden embedding
// lookup) that share a session_id and a sub-second timestamp. Showing
// both as separate rows is true to the data but useless to a non-
// engineer reading the table. We group them so the user sees ONE row
// per turn, with the underlying rows still available behind a toggle.
// Reset rows and unrelated operations are passed through as-is.
//
// Grouping rule: same session_id AND service === 'knowledge_base'/
// 'knowledge-base' AND timestamps within 60 seconds. The 60-second
// window is generous on purpose — embedding calls can lag a bit
// behind the streamed answer if the session is long-running.
// ─────────────────────────────────────────────────────────────────────────────

const KB_SERVICES = new Set(['knowledge-base', 'knowledge_base']);

// Window inside which an embedding lookup is considered to belong
// to a chat turn. STRICT session_id match is the primary gate; this
// 60s window is just a sanity guard against orphaned embeddings in
// a session whose chat_stream never logged (timeout / late retry).
// In normal operation it almost never matters because session_id
// alone uniquely identifies the turn.
const TURN_WINDOW_MS = 60_000;

const groupChatTurns = (logs) => {
  if (!logs || logs.length === 0) return [];
  const isKb = (r) => KB_SERVICES.has((r.service || '').toLowerCase());
  const ts  = (r) => new Date(r.timestamp || 0).getTime();

  // First pass: collect all chat_stream anchors.
  const anchorIdxs = [];
  for (let i = 0; i < logs.length; i++) {
    const r = logs[i];
    if (isKb(r) && r.operation === 'chat_stream') anchorIdxs.push(i);
  }

  // Second pass: pair each "internal" lookup (record_only KB row that
  // isn't a chat_stream — i.e. embedding/search) with its NEAREST
  // chat_stream within the window. Picking the nearest (smallest |Δt|)
  // is what makes two chat turns inside one session group correctly
  // (each embedding goes to the closest chat_stream, not the first one).
  //
  // Policy: STRICT session_id matching, no fallback. Both rows must
  // carry session_id and the values must match. This guarantees we
  // never accidentally merge across sessions even if timestamps are
  // close. The 60s window stays as a sanity guard against orphaned
  // embeddings within the same session.
  //
  // Backend contract: ws_chat_stream → search_knowledge_base →
  // hybrid_search → _report_embedding_usage now threads session_id
  // into the /quota/report payload (kb-lambda/shared/weaviate_utils.py).
  // Legacy rows written before that deploy have session_id=null on
  // search_embed and stay ungrouped (acceptable — they age out).
  const pairedAnchorOf = new Map(); // childIdx → anchorIdx
  for (let j = 0; j < logs.length; j++) {
    const c = logs[j];
    if (!isKb(c)) continue;
    if (c.operation === 'chat_stream') continue;
    if (!c.record_only) continue; // only fold internal lookups, not real ops
    const cTs = ts(c);
    let bestI = -1;
    let bestDelta = Infinity;
    for (const ai of anchorIdxs) {
      const a = logs[ai];
      if (!a.session_id || !c.session_id) continue;
      if (a.session_id !== c.session_id) continue;
      const delta = Math.abs(ts(a) - cTs);
      if (delta > TURN_WINDOW_MS) continue;
      if (delta < bestDelta) {
        bestDelta = delta;
        bestI = ai;
      }
    }
    if (bestI !== -1) pairedAnchorOf.set(j, bestI);
  }

  const consumed = new Set(pairedAnchorOf.keys());
  const grouped = [];
  for (let i = 0; i < logs.length; i++) {
    if (consumed.has(i)) continue;
    const row = logs[i];
    if (!isKb(row) || row.operation !== 'chat_stream') {
      grouped.push({ kind: 'single', row, children: [] });
      continue;
    }
    const cluster = {
      kind: 'cluster',
      row: { ...row },
      children: [],
    };
    for (const [childIdx, anchorIdx] of pairedAnchorOf.entries()) {
      if (anchorIdx !== i) continue;
      const candidate = logs[childIdx];
      cluster.children.push(candidate);
      cluster.row.input_tokens  += (candidate.input_tokens  || 0);
      cluster.row.output_tokens += (candidate.output_tokens || 0);
      cluster.row.total_tokens  += (candidate.total_tokens  || 0);
      cluster.row.cost_usd      += (candidate.cost_usd      || 0);
    }

    grouped.push(cluster);
  }
  return grouped;
};

// ─────────────────────────────────────────────────────────────────────────────
// Token Consumption tab
// ─────────────────────────────────────────────────────────────────────────────

function TokenConsumptionPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [windowDays, setWindowDays] = useState(30);
  const [includeResets, setIncludeResets] = useState(false);
  // "Show details" toggle for the Recent activity table. When OFF
  // (default) we collapse chat_stream + matching search_embed rows
  // into a single "SFXbot Chat" row so non-engineers can read the
  // table at a glance. When ON the raw row stream is rendered.
  const [showDetails, setShowDetails] = useState(false);
  // Chart-only window (defaults to 7d). The full `windowDays` above
  // controls how much data we PULL from the backend; this controls
  // how much of that we VISUALISE in the daily/weekly/monthly bar
  // chart. Decoupling the two lets a user keep "Last 30 days" as
  // their working window for activity / monthly history, while still
  // getting a tighter 7-day view of recent trend without a refetch.
  // When this exceeds `windowDays` we transparently clamp it down,
  // so the dropdown always feels honest about what it can show.
  const [chartWindowDays, setChartWindowDays] = useState(7);
  // Server-side pagination state for the Recent activity table.
  // `lambda_user_history` returns aggregates over the FULL window
  // and only paginates the `logs` array, so changing the page
  // re-fetches but it's a small payload (one page at a time).
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await quotaApi.get('/api/quota/me/history', {
        params: {
          days: windowDays,
          // Real backend pagination — sends page + page_size. The
          // lambda still ships full-window aggregates regardless of
          // page so totals/by_service/by_day stay stable as the user
          // pages through history.
          page,
          page_size: pageSize,
          // We always pull resets from the backend now because Fix B
          // (Monthly history) needs them to compute past-month totals.
          // The "Include resets" toggle is now purely a UI filter for
          // the Recent activity table.
          include_resets: 'true',
        },
      });
      setData(response.data);
    } catch (err) {
      const msg = err?.response?.data?.error || err?.message || 'Failed to load history';
      setError(msg);
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [windowDays, page, pageSize]);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  // When the data window or page size changes, snap back to page 1
  // — otherwise the user can land on a page that no longer exists
  // (e.g. switching from "Last 365 days" to "Last 7 days" might cut
  // total pages from 12 to 1).
  useEffect(() => {
    setPage(1);
  }, [windowDays, pageSize]);

  const summary = data?.summary;
  const totals = data?.totals;
  // ── Fix C: drop the "Period Resets" pseudo-service from the donut
  // and the by-service pill row. They aren't a service category, they're
  // historical markers. We keep them in `logs` for the activity table
  // (gated by `includeResets`) and surface them via the dedicated
  // Monthly history panel below. The hint count tells the viewer that
  // resets exist within the window without polluting the breakdown.
  const allByService = data?.by_service || [];
  const byService = useMemo(
    () => allByService.filter(s => !isResetService(s.service)),
    [allByService]
  );
  const resetServiceCount = useMemo(
    () => allByService.filter(s => isResetService(s.service)).reduce((a, s) => a + (s.calls || 0), 0),
    [allByService]
  );

  // The Recent activity table still respects the user's preference.
  // We slice the master logs array twice: once for the table view,
  // once for the monthly history (which always wants reset rows so
  // it can compute period-end totals).
  const allLogs = data?.logs || [];
  const logs = useMemo(
    () => (includeResets ? allLogs : allLogs.filter(r => !isResetOperation(r.operation))),
    [allLogs, includeResets]
  );

  // ── Fix A: bucket by_day into the right grain for the chosen window.
  // The chart-window dropdown is independent from the data-window
  // dropdown; clamp to whichever is smaller so we never claim to
  // show more days than we actually have data for.
  const effectiveChartDays = Math.min(chartWindowDays, windowDays);
  const grain = grainForWindow(effectiveChartDays);
  const chartBuckets = useMemo(() => {
    const allDays = data?.by_day || [];
    // Slice the most recent N days off the data window. by_day is
    // returned oldest→newest so we take from the tail.
    const days = effectiveChartDays >= allDays.length
      ? allDays
      : allDays.slice(-effectiveChartDays);
    const buckets = bucketByGrain(days, grain);
    if (buckets.length === 0) return [];
    const maxTokens = Math.max(...buckets.map(b => b.total_tokens || 0), 1);
    return buckets.map(b => ({
      ...b,
      heightPct: Math.max(2, Math.round((b.total_tokens / maxTokens) * 100))
    }));
  }, [data, grain, effectiveChartDays]);

  // ── Fix B: monthly history derived from reset snapshots + live usage.
  const monthlyHistory = useMemo(
    () => buildMonthlyHistory(allLogs, summary),
    [allLogs, summary]
  );
  const monthlyMax = useMemo(
    () => Math.max(...monthlyHistory.map(m => m.total_tokens || 0), 1),
    [monthlyHistory]
  );

  // ── Activity grouping (chat_stream + search_embed → "SFXbot Chat").
  const groupedRows = useMemo(
    () => (showDetails ? null : groupChatTurns(logs)),
    [logs, showDetails]
  );

  const pct = summary?.percentage_used ?? 0;
  const tone = getStatusTone(pct);
  const days = getDaysUntilReset(summary?.reset_date);

  return (
    <div className="profile-card token-card">
      <div className="profile-card-header token-card-header">
        <div>
          <h3 className="profile-card-title">
            <Activity size={18} className="card-title-icon" />
            Token Consumption
          </h3>
          <p className="token-card-subtitle">
            Your usage history and current monthly balance.
          </p>
        </div>
        <div className="token-card-controls">
          <select
            className="token-window-select"
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value))}
            disabled={loading}
            aria-label="History window"
          >
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={180}>Last 180 days</option>
            <option value={365}>Last 365 days</option>
          </select>
          <label className="token-toggle">
            <input
              type="checkbox"
              checked={includeResets}
              onChange={(e) => setIncludeResets(e.target.checked)}
              disabled={loading}
            />
            <span>Include resets</span>
          </label>
          <button
            className="token-refresh-btn"
            onClick={fetchHistory}
            disabled={loading}
            title="Refresh"
          >
            <RefreshCw size={14} className={loading ? 'spin' : ''} />
            <span>{loading ? 'Loading…' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      <div className="profile-card-body token-card-body">
        {error && (
          <div className="token-error">
            <AlertCircle size={16} />
            <span>{error}</span>
          </div>
        )}

        {/* ── Current period summary ─────────────────────────────── */}
        {summary && (
          <div className="token-summary-grid">
            <div className={`token-summary-tile tone-${tone}`}>
              <div className="tile-label">Current period</div>
              <div className="tile-value">
                {formatTokens(summary.current_usage)}
                <span className="tile-divider"> / </span>
                <span className="tile-limit">{formatTokens(summary.monthly_limit)}</span>
              </div>
              <div className="tile-bar-track">
                <div
                  className={`tile-bar-fill tone-${tone}`}
                  style={{ width: `${Math.min(100, pct)}%` }}
                />
              </div>
              <div className="tile-meta">
                <span>{pct.toFixed(1)}% used</span>
                <span>{formatTokens(summary.remaining_tokens)} left</span>
              </div>
            </div>

            <div className="token-summary-tile">
              <div className="tile-label">
                <Clock size={14} className="tile-label-icon" />
                Resets
              </div>
              <div className="tile-value">
                {days !== null && days > 0 ? `${days}d` : (days !== null ? 'Now' : '—')}
              </div>
              <div className="tile-meta tile-meta-single">
                {summary.reset_date
                  ? new Date(summary.reset_date).toLocaleDateString('en-US', {
                      month: 'short', day: 'numeric', year: 'numeric'
                    })
                  : 'No reset scheduled'}
              </div>
            </div>

            <div className="token-summary-tile">
              <div className="tile-label">Tier</div>
              <div className="tile-value tile-value-text">{summary.tier || 'free'}</div>
              <div className="tile-meta tile-meta-single">
                {formatCost(summary.current_cost_usd || 0)} this period
              </div>
            </div>
          </div>
        )}

        {/* ── Window totals ──────────────────────────────────────── */}
        {totals && (
          <div className="token-totals-row">
            <div className="totals-card">
              <div className="totals-label">
                <BarChart3 size={14} />
                Last {data.window_days} days
              </div>
              <div className="totals-grid">
                <div>
                  <div className="totals-num">{formatTokens(totals.total_tokens)}</div>
                  <div className="totals-cap">total tokens</div>
                </div>
                <div>
                  <div className="totals-num">{formatTokens(totals.input_tokens)}</div>
                  <div className="totals-cap">input</div>
                </div>
                <div>
                  <div className="totals-num">{formatTokens(totals.output_tokens)}</div>
                  <div className="totals-cap">output</div>
                </div>
                <div>
                  <div className="totals-num">{totals.call_count}</div>
                  <div className="totals-cap">requests</div>
                </div>
                <div>
                  <div className="totals-num">{formatCost(totals.cost_usd)}</div>
                  <div className="totals-cap">est. cost</div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ── Usage chart (auto-grain by chart window) ───────────────
            Has its OWN window selector (default 7d) decoupled from
            the activity/monthly window above. Options larger than
            the data window are disabled — we don't want to imply we
            can show 30 days of bars when the user only pulled 7. */}
        {chartBuckets.length > 0 && (
          <div className="token-chart-wrap">
            <div className="token-chart-header">
              <TrendingUp size={14} />
              <span>{grainLabel(grain)} usage</span>
              <span className="token-chart-grain-hint">
                {chartBuckets.length} bar{chartBuckets.length === 1 ? '' : 's'} · {effectiveChartDays}-day window
              </span>
              <select
                className="token-chart-window-select"
                value={chartWindowDays}
                onChange={(e) => setChartWindowDays(Number(e.target.value))}
                disabled={loading}
                aria-label="Chart window"
                title="Bar chart window — independent from the data window"
              >
                <option value={7}   disabled={windowDays < 7}>Last 7 days</option>
                <option value={14}  disabled={windowDays < 14}>Last 14 days</option>
                <option value={30}  disabled={windowDays < 30}>Last 30 days</option>
                <option value={90}  disabled={windowDays < 90}>Last 90 days</option>
                <option value={180} disabled={windowDays < 180}>Last 180 days</option>
                <option value={365} disabled={windowDays < 365}>Last 365 days</option>
              </select>
            </div>
            <div className="token-chart">
              {chartBuckets.map((b) => (
                <div
                  key={b.key}
                  className="chart-col"
                  title={`${b.label} • ${formatTokens(b.total_tokens)} tokens • ${formatCost(b.cost_usd)} • ${b.calls} request(s)`}
                >
                  <div className="chart-bar" style={{ height: `${b.heightPct}%` }} />
                </div>
              ))}
            </div>
            <div className="token-chart-axis">
              <span>{chartBuckets[0].label}</span>
              {chartBuckets.length > 1 && <span>{chartBuckets[chartBuckets.length - 1].label}</span>}
            </div>
          </div>
        )}

        {/* ── Monthly history (Fix B) ─────────────────────────────────
            Derived from period_reset snapshots + live current usage.
            Always renders when there is at least one month of data
            (almost always true after the first reset cycle). Reads
            very differently from the windowed bar chart above: this is
            a "lifetime monthly billing" view, NOT bound by `windowDays`. */}
        {monthlyHistory.length > 0 && (
          <div className="token-section token-monthly-section">
            <div className="token-section-title">
              <BarChart3 size={14} />
              <span>Monthly history</span>
              <span className="token-section-hint">
                from period resets · {monthlyHistory.length} month{monthlyHistory.length === 1 ? '' : 's'}
              </span>
            </div>
            <div className="token-monthly-grid">
              {monthlyHistory.map(m => {
                const pct = Math.max(2, Math.round((m.total_tokens / monthlyMax) * 100));
                return (
                  <div
                    key={m.key}
                    className={`token-monthly-col ${m.source === 'live' ? 'is-live' : ''}`}
                    title={`${m.label}${m.source === 'live' ? ' (in progress)' : ''} • ${formatTokens(m.total_tokens)} tokens • ${formatCost(m.cost_usd)}`}
                  >
                    <div className="token-monthly-bar-track">
                      <div className="token-monthly-bar-fill" style={{ height: `${pct}%` }} />
                    </div>
                    <div className="token-monthly-num">{formatTokens(m.total_tokens)}</div>
                    <div className="token-monthly-label">
                      {m.label}
                      {m.source === 'live' && <span className="token-monthly-live-pill">now</span>}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── By service ─────────────────────────────────────────────
            Period Resets (service='system') are filtered out here on
            purpose: they're not a service the user consumed against,
            they're historical bookmarks. The hint below makes that
            transparent so the totals don't look like they're missing
            data. Reset rows still appear in Recent activity (when the
            "Include resets" toggle is on) and drive the Monthly
            history panel above. */}
        {byService.length > 0 && (
          <div className="token-section">
            <div className="token-section-title">
              By service
              {resetServiceCount > 0 && (
                <span className="token-section-hint">
                  · {resetServiceCount} period reset{resetServiceCount === 1 ? '' : 's'} excluded
                </span>
              )}
            </div>
            <div className="service-row">
              {byService.map((s) => (
                <div key={s.service} className="service-pill">
                  <div className="service-pill-name">{SERVICE_LABELS[s.service] || s.service}</div>
                  <div className="service-pill-num">{formatTokens(s.total_tokens)}</div>
                  <div className="service-pill-meta">
                    {s.calls} call{s.calls === 1 ? '' : 's'} · {formatCost(s.cost_usd)}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Recent activity table ──────────────────────────────────
            Two render modes:
              - default (showDetails=false) → chat_stream + matching
                search_embed are collapsed into a single "SFXbot Chat"
                row labelled with the conversation totals. This is the
                view a non-engineer should see — one row per chat turn.
              - showDetails=true → raw row stream as the lambda returns
                it, useful for debugging billing or audit chains.
            Pagination/scroll: the wrap below is overflow-y:auto, capped
            at ~520px tall so very long histories stay scrollable
            without breaking the page. The lambda already applies a
            500-row cap and tells us via `truncated` whether older rows
            were cut off. */}
        <div className="token-section">
          <div className="token-section-title">
            Recent activity
            <span className="token-section-hint">
              {showDetails
                ? '\u00b7 raw events (every embedding lookup shown separately)'
                : '\u00b7 1 row per chat turn (embedding lookups merged in)'}
            </span>
            <label
              className="token-toggle token-toggle-inline"
              title={
                showDetails
                  ? 'Uncheck to merge each chat turn\u2019s embedding lookups into one row.'
                  : 'Check to expand each chat turn into its raw events (chat + embedding lookups).'
              }
            >
              <input
                type="checkbox"
                checked={showDetails}
                onChange={(e) => setShowDetails(e.target.checked)}
                disabled={loading}
              />
              <span>Show details</span>
            </label>
            {data?.truncated && (
              <span className="token-truncated-hint">
                showing latest {allLogs.length} of {data.logs_total_in_window}
              </span>
            )}
          </div>
          {logs.length === 0 ? (
            <div className="token-empty">
              {loading ? 'Loading…' : 'No usage recorded in this window.'}
            </div>
          ) : (
            <div className="token-log-table-wrap">
              <table className="token-log-table">
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Operation</th>
                    <th className="num">Input</th>
                    <th className="num">Output</th>
                    <th className="num">Total</th>
                    <th className="num">Cost</th>
                    <th>Model</th>
                  </tr>
                </thead>
                <tbody>
                  {showDetails
                    ? logs.map((row) => {
                        const opLabel = OPERATION_LABELS[row.operation] || row.operation || '—';
                        const isReset = isResetOperation(row.operation);
                        return (
                          <tr key={row.id} className={isReset ? 'row-reset' : (row.record_only ? 'row-record-only' : '')}>
                            <td className="cell-when">{formatTimestamp(row.timestamp)}</td>
                            <td>
                              <span className="cell-operation">{opLabel}</span>
                              {row.record_only && (
                                <span
                                  className="badge badge-audit"
                                  title="Audit only — this event (e.g. an embedding lookup performed during a chat turn) is logged for cost analytics but is NOT deducted from your monthly token quota."
                                >audit</span>
                              )}
                              {isReset && (
                                <span className="badge badge-reset" title="Period reset snapshot">reset</span>
                              )}
                            </td>
                            <td className="num">{formatTokens(row.input_tokens)}</td>
                            <td className="num">{formatTokens(row.output_tokens)}</td>
                            <td className="num strong">{formatTokens(row.total_tokens)}</td>
                            <td className="num cost">{formatCost(row.cost_usd)}</td>
                            <td className="cell-model">{row.model || '—'}</td>
                          </tr>
                        );
                      })
                    : (groupedRows || []).map((entry, idx) => {
                        const row = entry.row;
                        const isCluster = entry.kind === 'cluster';
                        const isReset = isResetOperation(row.operation);
                        const opLabel = isCluster
                          ? 'SFXbot Chat'
                          : (OPERATION_LABELS[row.operation] || row.operation || '—');
                        const childCount = entry.children?.length || 0;
                        return (
                          <tr
                            key={row.id || `${entry.kind}-${idx}`}
                            className={isReset ? 'row-reset' : (row.record_only ? 'row-record-only' : '')}
                          >
                            <td className="cell-when">{formatTimestamp(row.timestamp)}</td>
                            <td>
                              <span className="cell-operation">{opLabel}</span>
                              {isCluster && childCount > 0 && (
                                <span
                                  className="badge badge-rollup"
                                  title={`This row already includes the tokens from ${childCount} internal embedding lookup${childCount === 1 ? '' : 's'} that ran for this chat turn. Toggle "Show details" if you want to see them as separate rows.`}
                                >
                                  +{childCount} internal
                                </span>
                              )}
                              {!isCluster && row.record_only && (
                                <span
                                  className="badge badge-audit"
                                  title="Audit only — this event (e.g. an embedding lookup performed during a chat turn) is logged for cost analytics but is NOT deducted from your monthly token quota."
                                >audit</span>
                              )}
                              {isReset && (
                                <span className="badge badge-reset" title="Period reset snapshot">reset</span>
                              )}
                            </td>
                            <td className="num">{formatTokens(row.input_tokens)}</td>
                            <td className="num">{formatTokens(row.output_tokens)}</td>
                            <td className="num strong">{formatTokens(row.total_tokens)}</td>
                            <td className="num cost">{formatCost(row.cost_usd)}</td>
                            <td className="cell-model">{row.model || '—'}</td>
                          </tr>
                        );
                      })
                  }
                </tbody>
              </table>
              {/* Pagination footer — only renders when the lambda
                  reports it ran in paginated mode AND there's more
                  than one page. Single-page results stay clean (no
                  visual noise). The "Showing X–Y of N" block doubles
                  as a sanity check for the grouped vs raw view —
                  X..Y refers to RAW row positions in the response
                  page, not visible row count after grouping. */}
              {data?.pagination?.mode === 'paginated' && data.pagination.total_pages > 1 && (
                <div className="token-pagination">
                  <div className="token-pagination-info">
                    Showing{' '}
                    <strong>{(data.pagination.page - 1) * data.pagination.page_size + 1}</strong>
                    {'\u2013'}
                    <strong>{Math.min(data.pagination.page * data.pagination.page_size, data.pagination.total)}</strong>
                    {' '}of <strong>{data.pagination.total}</strong> events
                  </div>
                  <div className="token-pagination-controls">
                    <select
                      className="token-page-size-select"
                      value={pageSize}
                      onChange={(e) => setPageSize(Number(e.target.value))}
                      disabled={loading}
                      aria-label="Rows per page"
                      title="Rows per page"
                    >
                      <option value={10}>10 / page</option>
                      <option value={25}>25 / page</option>
                      <option value={50}>50 / page</option>
                      <option value={100}>100 / page</option>
                    </select>
                    <button
                      type="button"
                      className="token-page-btn"
                      onClick={() => setPage(p => Math.max(1, p - 1))}
                      disabled={loading || data.pagination.page <= 1}
                    >
                      ‹ Prev
                    </button>
                    <span className="token-page-indicator">
                      Page {data.pagination.page} of {data.pagination.total_pages}
                    </span>
                    <button
                      type="button"
                      className="token-page-btn"
                      onClick={() => setPage(p => Math.min(data.pagination.total_pages, p + 1))}
                      disabled={loading || !data.pagination.has_more}
                    >
                      Next ›
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Profile page (existing identity card + new consumption panel)
// ─────────────────────────────────────────────────────────────────────────────

function ProfilePage() {
  const [userInfo, setUserInfo] = useState({
    fullName: '',
    email: '',
    username: '',
    picture: null,
    dateJoined: '',
    role: 'User'
  });

  useEffect(() => {
    const loadUserInfo = () => {
      try {
        const storedUser = localStorage.getItem('user');
        if (storedUser) {
          const userData = JSON.parse(storedUser);
          
          // Format the date from created_at
          let formattedDate = 'Unknown';
          if (userData.created_at) {
            formattedDate = new Date(userData.created_at).toLocaleDateString('en-US', {
              year: 'numeric',
              month: 'long',
              day: 'numeric'
            });
          }
          
          setUserInfo({
            fullName: userData.fullname || userData.name || `${userData.first_name || ''} ${userData.last_name || ''}`.trim() || 'User',
            email: userData.gmail || userData.email || '',
            username: userData.gmail?.split('@')[0] || userData.username || '',
            picture: userData.picture || null,
            dateJoined: formattedDate,
            role: userData.role || (userData.is_staff ? 'Admin' : 'User')
          });
        }
      } catch (error) {
        console.error('Error loading user info:', error);
      }
    };

    loadUserInfo();
  }, []);

  return (
    <div className="profile-page">
      <div className="profile-container">
        <div className="profile-header">
          <h1 className="profile-title">My Profile</h1>
          <p className="profile-subtitle">Manage your account information</p>
        </div>

        <div className="profile-content">
          {/* Profile Card */}
          <div className="profile-card">
            <div className="profile-card-header">
              <div className="profile-avatar-section">
                <div className="profile-avatar-large">
                  {userInfo.picture ? (
                    <img 
                      src={userInfo.picture} 
                      alt={userInfo.fullName}
                      className="profile-avatar-img"
                      onError={(e) => {
                        e.target.style.display = 'none';
                        e.target.nextSibling.style.display = 'flex';
                      }}
                    />
                  ) : null}
                  <div 
                    className="profile-avatar-icon"
                    style={{ display: userInfo.picture ? 'none' : 'flex' }}
                  >
                    <User size={48} strokeWidth={1.5} />
                  </div>
                </div>
                <div className="profile-name-section">
                  <h2 className="profile-name">
                    {userInfo.fullName}
                  </h2>
                  <p className="profile-username">@{userInfo.username}</p>
                </div>
              </div>
            </div>

            <div className="profile-card-body">
              <div className="profile-info-grid">
                {/* Full Name */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <User size={18} />
                    <span>Full Name</span>
                  </div>
                  <div className="profile-info-value">
                    {userInfo.fullName}
                  </div>
                </div>

                {/* Username */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <User size={18} />
                    <span>Username</span>
                  </div>
                  <div className="profile-info-value">
                    {userInfo.username}
                  </div>
                </div>

                {/* Email */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <Mail size={18} />
                    <span>Email</span>
                  </div>
                  <div className="profile-info-value">
                    {userInfo.email}
                  </div>
                </div>

                {/* Role */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <Shield size={18} />
                    <span>Role</span>
                  </div>
                  <div className="profile-info-value">
                    <span className="profile-role-badge">{userInfo.role}</span>
                  </div>
                </div>

                {/* Date Joined */}
                <div className="profile-info-item">
                  <div className="profile-info-label">
                    <Calendar size={18} />
                    <span>Member Since</span>
                  </div>
                  <div className="profile-info-value">
                    {userInfo.dateJoined}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Token Consumption section (new) */}
          <TokenConsumptionPanel />

          {/* Additional Info Card */}
          <div className="profile-card">
            <div className="profile-card-header">
              <h3 className="profile-card-title">Account Information</h3>
            </div>
            <div className="profile-card-body">
              <div className="profile-info-notice">
                <Shield size={24} className="notice-icon" />
                <div>
                  <h4>Google Account</h4>
                  <p>Your profile information is managed through your Google account. To update your name, email, or profile picture, please visit your Google Account settings.</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ProfilePage;
