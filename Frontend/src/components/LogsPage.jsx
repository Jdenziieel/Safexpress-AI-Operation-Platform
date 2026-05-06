import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Activity, Clock, CheckCircle, XCircle, AlertTriangle, RefreshCw,
  TrendingUp, TrendingDown, Server, Zap, BarChart3,
  Shield, DollarSign, Cpu, Edit3, Save, Calendar, AlertCircle,
  Search, ChevronUp, FileText, MessageSquare, Bot
} from 'lucide-react';
import '../css/LogsPage.css';
import { supervisorApi, kbApi } from '../api';

// All requests below go through `supervisorApi` (axios instance in api.js)
// which auto-attaches `Authorization: Bearer <JWT>` via its request
// interceptor. The base URL is controlled by VITE_SUPERVISOR_URL — set it
// in Frontend/.env.production (or your CI build env) to the supervisor's
// API Gateway URL on cutover; defaults to http://localhost:8010 for dev.
//
// IMPORTANT: do NOT switch back to raw `fetch()` here. The deployed
// supervisor sits behind `jwt-api-authorizer`, which 401s any request
// missing the Bearer header. See AuthUpdate.md §2.2 for the admin routes.

// =============================================================================
// TIME PERIOD SELECTOR COMPONENT
// =============================================================================
const TimePeriodSelector = ({ selectedPeriod, onPeriodChange }) => {
  const periods = [
    { value: '1h', label: 'Last Hour' },
    { value: '24h', label: 'Last 24 Hours' },
    { value: '7d', label: 'Last 7 Days' },
    { value: '30d', label: 'Last 30 Days' }
  ];

  return (
    <div className="time-period-selector">
      <Calendar size={16} />
      <select
        value={selectedPeriod}
        onChange={(e) => onPeriodChange(e.target.value)}
        className="period-select"
      >
        {periods.map(period => (
          <option key={period.value} value={period.value}>
            {period.label}
          </option>
        ))}
      </select>
    </div>
  );
};

// =============================================================================
// SHARED FORMATTERS
// =============================================================================
// Hoisted to module scope (was local to TokenCostTab) so the Performance
// tab's KB Document/Chat Analytics blocks can render the same dollar-and-
// token strings as the Token & Cost tab — keeps the two surfaces visually
// consistent when admins switch tabs.
const formatTokens = (t) => {
  if (!t) return '0';
  if (t >= 1_000_000) return `${(t / 1_000_000).toFixed(2)}M`;
  if (t >= 1_000) return `${(t / 1_000).toFixed(1)}K`;
  return t.toLocaleString();
};

const formatCost = (c) => {
  if (!c) return '$0.00';
  return `$${parseFloat(c).toFixed(4)}`;
};

const formatMs = (ms) => {
  if (ms == null || ms === 0) return 'N/A';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
};

// =============================================================================
// STATS CARD COMPONENT
// =============================================================================
const StatsCard = ({ icon: Icon, title, value, subtitle, trend, trendDirection }) => (
  <div className="stats-card">
    <div className="stats-card-header">
      <div className="stats-icon">
        <Icon size={24} />
      </div>
      <div className="stats-trend">
        {trend && (
          <span className={`trend ${trendDirection}`}>
            {trendDirection === 'up' ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
            {trend}
          </span>
        )}
      </div>
    </div>
    <div className="stats-card-body">
      <h3 className="stats-value">{value}</h3>
      <p className="stats-title">{title}</p>
      {subtitle && <span className="stats-subtitle">{subtitle}</span>}
    </div>
  </div>
);

// =============================================================================
// AI ASSISTANT ANALYTICS BLOCK
// =============================================================================
// Block of conversation-thread + request totals from the AI Assistant
// (supervisor-agent) surface.  Renamed from "Conversations" to
// "Conversation Threads" because admins were reading "conversation" as
// a single turn — but each row counts a UNIQUE thread_id (one user
// back-and-forth = one thread regardless of how many messages it
// contains), which is what the metric represents.
//
// Renamed again Mon-4-May from "Conversation Threads & Requests" to
// "AI Assistant Analytics" so it parallels the "SFX Bot Chat
// Analytics" + "Document Analytics" sections it now sits next to.
// The page-level period selector still drives the window (1h/24h/
// 7d/30d). The card subtitle keeps the explicit "Conversation
// Threads" / "Requests" labels so admins still see what the two
// numbers actually represent.
//
// As of Sun-3-May the block follows the period selector at the top of
// the Admin Dashboard (was previously hard-coded to 24h/7d/30d side-
// by-side, which left admins with 6 cards covering 3 windows and no
// way to focus on the one they actually wanted). The selector emits
// {1h, 24h, 7d, 30d}; the backend `/admin/usage/summary` only computes
// {today (24h), this_week (7d), this_month (30d)}, so 1h falls back to
// today with a small caveat in the subtitle (no separate 1h scan
// today — the gain wouldn't be worth the table-scan cost).
//
// Position: moved Mon-4-May to render AFTER "SFX Bot Chat Analytics"
// inside AgentPerformanceTab (was previously at the top above the
// system-wide metrics). The new layout reads naturally as "system
// metrics → KB document ingestion → SFX Bot end-user chat → AI
// Assistant end-user chat", grouping the two end-user surfaces
// together at the bottom.
const PERIOD_TO_USAGE_KEY = {
  '1h':  'today',
  '24h': 'today',
  '7d':  'this_week',
  '30d': 'this_month',
};

const PERIOD_LABELS = {
  '1h':  'last hour',
  '24h': 'last 24 hours',
  '7d':  'last 7 days',
  '30d': 'last 30 days',
};

const PERIOD_ICONS = {
  '1h':  Clock,
  '24h': Clock,
  '7d':  Calendar,
  '30d': BarChart3,
};

const UsageBlock = ({ usageData, loading, timePeriod = '24h' }) => {
  if (loading) {
    return (
      <div className="token-tab-loading">
        <RefreshCw size={24} className="spin" />
        <span>Loading usage data...</span>
      </div>
    );
  }

  if (!usageData) {
    return (
      <div className="no-data">
        <Activity size={48} />
        <p>No usage data available</p>
        <span>Usage statistics will appear once the system processes requests</span>
      </div>
    );
  }

  const usageKey = PERIOD_TO_USAGE_KEY[timePeriod] || 'today';
  const periodLabel = PERIOD_LABELS[timePeriod] || PERIOD_LABELS['24h'];
  const Icon = PERIOD_ICONS[timePeriod] || Clock;
  const d = usageData[usageKey] || {};
  // 1h is a graceful-degradation case — backend has no per-hour
  // bucket, so we show the 24h numbers and label them honestly.
  // Any other selection matches the backend window exactly.
  const isFallback = (timePeriod === '1h');
  const cardLabel = isFallback ? 'last 24 hours' : periodLabel;

  return (
    <div className="usage-block">
      <div className="services-header" style={{ marginTop: 40 }}>
        <h2><BarChart3 size={20} /> AI Assistant Analytics</h2>
        <p>
          End-user AI Assistant chat activity for the <strong>{periodLabel}</strong>, driven by the period selector above.
          {isFallback && (
            <>
              {' '}
              <em style={{ color: '#94a3b8' }}>
                (No per-hour window available &mdash; showing the 24h totals.)
              </em>
            </>
          )}
        </p>
      </div>
      <div className="stats-grid" style={{ marginBottom: 32 }}>
        <StatsCard
          icon={Icon}
          title={`Conversation Threads \u2014 ${cardLabel}`}
          value={(d.conversations || 0).toLocaleString()}
          subtitle="Unique threads (each is one user back-and-forth)"
        />
        <StatsCard
          icon={Zap}
          title={`Requests \u2014 ${cardLabel}`}
          value={(d.requests || 0).toLocaleString()}
          subtitle="Total user messages processed"
        />
      </div>
    </div>
  );
};

// =============================================================================
// BUDGET BANNER
// =============================================================================
const BudgetBanner = ({ budget }) => {
  if (!budget) return null;
  if (budget.over_budget) {
    return (
      <div className="health-banner health-critical">
        <div className="health-content">
          <AlertCircle size={20} />
          <span className="health-status">
            Over budget! Spent ${(budget.current_month_cost_usd || 0).toFixed(4)} of ${(budget.monthly_budget_usd || 0).toFixed(2)} ({budget.pct_used}%)
          </span>
        </div>
      </div>
    );
  }
  if (budget.alert_triggered) {
    return (
      <div className="health-banner health-warning">
        <div className="health-content">
          <AlertTriangle size={20} />
          <span className="health-status">
            Budget warning: {budget.pct_used}% used — ${(budget.current_month_cost_usd || 0).toFixed(4)} of ${(budget.monthly_budget_usd || 0).toFixed(2)}
          </span>
        </div>
      </div>
    );
  }
  return null;
};

// =============================================================================
// TOKEN USAGE + PRICING EDITOR + BUDGET TAB
// =============================================================================
// `budgetData` is still passed in (read-only) so the BudgetBanner at
// the top of this tab can render warn/over-budget states. The editor
// itself moved to the Token Management page (QuotaPage) on 2026-05-04
// — see the comment around `<BudgetBanner>` below.
const TokenCostTab = ({ tokenData, tokenLoading, pricingData, budgetData, onSaveRate }) => {
  const [editingModel, setEditingModel] = useState(null);
  const [editInputRate, setEditInputRate] = useState('');
  const [editOutputRate, setEditOutputRate] = useState('');
  const [savingRate, setSavingRate] = useState(false);
  // Model pricing table — search + pagination. The full pricing
  // table now spans 20+ models (gpt-4 / gpt-4o / gpt-4.1 / gpt-5.x /
  // o1 / o3 / o4 families) so a single scroll-forever list became
  // unusable. Search is applied first (case-insensitive substring
  // on the model name), then the result is sliced by page.
  const [pricingSearch, setPricingSearch] = useState('');
  const [pricingPage, setPricingPage] = useState(1);
  const PRICING_PAGE_SIZE = 8;

  const startEditing = (model) => {
    setEditingModel(model.model);
    setEditInputRate(String(model.input_rate_per_1k));
    setEditOutputRate(String(model.output_rate_per_1k));
  };

  const cancelEditing = () => {
    setEditingModel(null);
  };

  const handleSaveRate = async (modelName) => {
    const inputRate = parseFloat(editInputRate);
    const outputRate = parseFloat(editOutputRate);
    if (isNaN(inputRate) || isNaN(outputRate) || inputRate <= 0 || outputRate <= 0) return;
    setSavingRate(true);
    await onSaveRate(modelName, inputRate, outputRate);
    setSavingRate(false);
    setEditingModel(null);
  };

  // Token summary from existing /logs/stats
  const summary = tokenData?.token_summary;
  const totals = summary?.totals || {};
  const byModel = summary?.by_model || [];
  const byTier = summary?.by_tier || [];
  const hasTokenData = (totals.total_calls || 0) > 0;

  const maxTokens = byModel.reduce((m, r) => Math.max(m, r.tokens || 0), 1);

  const getTierLabel = (tier) => {
    const labels = {
      // Supervisor-agent tiers — labels match the names admins see
      // throughout the rest of the dashboard (QuotaPage history modal,
      // execution log traces).  Avoid abbreviations: "Fmt" was opaque
      // to anyone who hadn't read the source ("formatter" tier name).
      '0.5':            'Quick Check (Tier 0.5)',
      '1':              'Full Analysis (Tier 1)',
      'classifier':     'Agent Classifier',
      // Backend was renamed supervisor → planner so the canonical name
      // matches LOGS_ANALYTICS_MIGRATION_CONTRACT and stops getting
      // dropped by ALLOWED_TIERS. The 'supervisor' alias is kept here
      // so historical rows (written before the rename) still render
      // as "Plan Generation" instead of "Other".
      'planner':        'Plan Generation',
      'supervisor':     'Plan Generation',
      'formatter':      'Response Formatting',
      'memory':         'Memory',
      'post':           'Post-Processing',
      'enrichment':     'Enrichment',
      'orchestrator':   'LLM Transform',
      'transform':      'LLM Transform',
      'summarization':  'Summarization',
      // Knowledge-base tiers (chat_message / kb_query / ws_chat_stream / pdf_parse)
      'chat':           'KB Chat (RAG)',
      'document':       'Document Parse',
      // Last-resort bucket for rows that ALLOWED_TIERS rejected at
      // write time (or that pre-dated the current tier set).  Render
      // it as a friendlier "Other" so admins don't think it's a
      // system error.  Backfill the underlying rows in DynamoDB
      // (Sup_LLMCalls.tier) if you want to make them disappear from
      // this bucket.
      'unknown':        'Other / Unmapped',
    };
    return labels[tier] || tier || 'Other';
  };

  const models = pricingData?.models || [];

  // Apply search → paginate. Memoization keeps the slice stable across
  // unrelated re-renders (token stats refresh every 30s and would
  // otherwise force a recompute on every tick).
  const filteredModels = useMemo(() => {
    const q = pricingSearch.trim().toLowerCase();
    if (!q) return models;
    return models.filter((m) => (m.model || '').toLowerCase().includes(q));
  }, [models, pricingSearch]);

  // Input / Output cost split for the "Estimated Cost" card subtitle.
  // The backend stores total estimated_cost_usd per row but does NOT
  // break it down by direction (the column was added before per-direction
  // pricing existed). Compute it client-side from the per-model breakdown:
  // if the model is in the pricing table, use its real input_rate_per_1k
  // and output_rate_per_1k; if it isn't (e.g. a model that was used once
  // and later removed from pricing), fall back to allocating its cost
  // proportionally by token count so the two halves always sum back to
  // the headline total. Empty / no-token rows are skipped to avoid
  // divide-by-zero.
  const costSplit = useMemo(() => {
    const rateLookup = new Map(
      models.map((m) => [
        (m.model || '').toLowerCase(),
        {
          input: parseFloat(m.input_rate_per_1k) || 0,
          output: parseFloat(m.output_rate_per_1k) || 0,
        },
      ])
    );
    let inputCost = 0;
    let outputCost = 0;
    for (const row of byModel) {
      const inputTokens = parseInt(row.input_tokens || 0, 10) || 0;
      const outputTokens = parseInt(row.output_tokens || 0, 10) || 0;
      const rowCost = parseFloat(row.cost_usd || 0) || 0;
      const rates = rateLookup.get((row.model || '').toLowerCase());
      if (rates && (rates.input > 0 || rates.output > 0)) {
        inputCost += (inputTokens / 1000) * rates.input;
        outputCost += (outputTokens / 1000) * rates.output;
      } else if (inputTokens + outputTokens > 0) {
        const inShare = inputTokens / (inputTokens + outputTokens);
        inputCost += rowCost * inShare;
        outputCost += rowCost * (1 - inShare);
      }
    }
    return { inputCost, outputCost };
  }, [byModel, models]);

  const pricingTotalPages = Math.max(1, Math.ceil(filteredModels.length / PRICING_PAGE_SIZE));
  // Clamp current page when filter shrinks the list below the current page.
  const safePricingPage = Math.min(pricingPage, pricingTotalPages);
  const pricingPageStart = (safePricingPage - 1) * PRICING_PAGE_SIZE;
  const pagedModels = filteredModels.slice(pricingPageStart, pricingPageStart + PRICING_PAGE_SIZE);

  return (
    <div className="token-usage-tab">
      {/* Budget Banner — read-only on this page. The Monthly Budget
          editor was moved to the Token Management page (QuotaPage)
          on 2026-05-04 per user request so saving a budget produces an
          audit row in the Admin Actions panel there. The banner stays
          on the Admin Dashboard so a sudden warn/over-budget state is
          still visible to anyone landing on this page. */}
      <BudgetBanner budget={budgetData} />

      {/* Token Stats */}
      {tokenLoading ? (
        <div className="token-tab-loading">
          <RefreshCw size={24} className="spin" />
          <span>Loading token data...</span>
        </div>
      ) : hasTokenData ? (
        <>
          <div className="stats-grid">
            <StatsCard icon={Cpu} title="Total LLM Calls" value={(totals.total_calls || 0).toLocaleString()} subtitle={`${totals.successful_calls || 0} succeeded, ${totals.failed_calls || 0} failed`} />
            <StatsCard icon={Zap} title="Total Tokens" value={formatTokens(totals.total_tokens)} subtitle={`In: ${formatTokens(totals.total_input_tokens)} / Out: ${formatTokens(totals.total_output_tokens)}`} />
            <StatsCard icon={DollarSign} title="Estimated Cost" value={formatCost(totals.total_cost_usd)} subtitle={`In: ${formatCost(costSplit.inputCost)} / Out: ${formatCost(costSplit.outputCost)}`} />
            <StatsCard icon={Clock} title="Avg Latency" value={totals.avg_duration_ms ? `${(totals.avg_duration_ms / 1000).toFixed(2)}s` : 'N/A'} subtitle="Per LLM call" />
          </div>

          {/* Cost by Model table */}
          {byModel.length > 0 && (
            <div className="token-section">
              <h2><Cpu size={20} /> Cost by Model</h2>
              <div className="token-model-table">
                <div className="token-table-header">
                  <span className="col-model">Model</span>
                  <span className="col-calls">Calls</span>
                  <span className="col-tokens">Input</span>
                  <span className="col-tokens">Output</span>
                  <span className="col-tokens">Total</span>
                  <span className="col-cost">Cost</span>
                  <span className="col-bar">Share</span>
                </div>
                {byModel.map((row) => (
                  <div key={row.model} className="token-table-row">
                    <span className="col-model"><Cpu size={14} />{row.model}</span>
                    <span className="col-calls">{row.calls}</span>
                    <span className="col-tokens">{formatTokens(row.input_tokens)}</span>
                    <span className="col-tokens">{formatTokens(row.output_tokens)}</span>
                    <span className="col-tokens">{formatTokens(row.tokens)}</span>
                    <span className="col-cost">{formatCost(row.cost_usd)}</span>
                    <span className="col-bar">
                      <div className="token-bar-track">
                        <div className="token-bar-fill" style={{ width: `${((row.tokens || 0) / maxTokens) * 100}%` }} />
                      </div>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Usage by Tier */}
          {byTier.length > 0 && (
            <div className="token-section">
              <h2><BarChart3 size={20} /> Usage by Tier</h2>
              <div className="token-tier-list">
                {byTier.map((row) => {
                  const pct = totals.total_tokens ? ((row.tokens || 0) / totals.total_tokens * 100) : 0;
                  return (
                    <div key={row.tier || 'none'} className="token-tier-item">
                      <div className="tier-info">
                        <span className="tier-name">{getTierLabel(row.tier)}</span>
                        <span className="tier-stats">{row.calls} calls &middot; {formatTokens(row.tokens)} tokens &middot; {formatCost(row.cost_usd)}</span>
                      </div>
                      <div className="tier-bar-track">
                        <div className="tier-bar-fill" style={{ width: `${pct}%` }} />
                      </div>
                      <span className="tier-pct">{pct.toFixed(1)}%</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="no-data">
          <DollarSign size={48} />
          <p>No token usage data yet</p>
          <span>Token consumption will appear here once the supervisor processes tasks</span>
        </div>
      )}

      {/* Pricing Editor */}
      <div className="token-section">
        <h2><Edit3 size={20} /> Model Pricing Rates</h2>
        <p style={{ fontSize: 13, color: '#6b7280', marginTop: -8, marginBottom: 16 }}>
          Rate changes apply to future usage only. Historical costs are preserved.
        </p>
        {/* Search + result count. Wrapper inherits the budget-controls
            flex layout so it sits flush above the table without needing
            new CSS. The result count helps admins know whether their
            search actually narrowed anything down (e.g. typing "gpt"
            still returns 18 rows). */}
        {models.length > 0 && (
          <div className="budget-controls" style={{ marginBottom: 16, alignItems: 'flex-end' }}>
            <div className="budget-field" style={{ flex: 1, minWidth: 240 }}>
              <label>Search models</label>
              <div style={{ position: 'relative' }}>
                <Search
                  size={14}
                  style={{
                    position: 'absolute',
                    left: 10,
                    top: '50%',
                    transform: 'translateY(-50%)',
                    color: '#6b7280',
                    pointerEvents: 'none',
                  }}
                />
                <input
                  type="text"
                  value={pricingSearch}
                  onChange={(e) => {
                    setPricingSearch(e.target.value);
                    setPricingPage(1);
                  }}
                  placeholder="e.g. gpt-4.1, o1, mini"
                  className="budget-input"
                  style={{ paddingLeft: 32, width: '100%' }}
                />
              </div>
            </div>
            <div style={{ fontSize: 12, color: '#6b7280', paddingBottom: 10 }}>
              Showing {filteredModels.length === 0 ? 0 : pricingPageStart + 1}
              –{Math.min(pricingPageStart + PRICING_PAGE_SIZE, filteredModels.length)}
              {' '}of {filteredModels.length}
              {pricingSearch && filteredModels.length !== models.length
                ? ` (filtered from ${models.length})`
                : ''}
            </div>
          </div>
        )}
        {models.length > 0 && filteredModels.length === 0 ? (
          <div className="no-data" style={{ padding: 32 }}>
            <Search size={28} />
            <p>No models match "{pricingSearch}"</p>
            <button
              className="refresh-btn"
              style={{ padding: '6px 14px', fontSize: 12, marginTop: 8 }}
              onClick={() => { setPricingSearch(''); setPricingPage(1); }}
            >
              Clear search
            </button>
          </div>
        ) : models.length > 0 ? (
          <div className="token-model-table">
            <div className="token-table-header" style={{ gridTemplateColumns: '2fr 1.2fr 1.2fr 1fr 1fr 0.8fr 0.8fr' }}>
              <span className="col-model">Model</span>
              <span className="col-cost">Input Rate ($/1K)</span>
              <span className="col-cost">Output Rate ($/1K)</span>
              <span className="col-tokens">Input Tokens</span>
              <span className="col-tokens">Output Tokens</span>
              <span className="col-cost">Total Cost</span>
              <span>Actions</span>
            </div>
            {pagedModels.map((m) => (
              <div key={m.model} className="token-table-row" style={{ gridTemplateColumns: '2fr 1.2fr 1.2fr 1fr 1fr 0.8fr 0.8fr' }}>
                <span className="col-model"><Cpu size={14} />{m.model}</span>
                {editingModel === m.model ? (
                  <>
                    <span className="col-cost">
                      <input type="number" step="0.00001" min="0" value={editInputRate} onChange={e => setEditInputRate(e.target.value)} className="budget-input" style={{ width: 90 }} />
                    </span>
                    <span className="col-cost">
                      <input type="number" step="0.00001" min="0" value={editOutputRate} onChange={e => setEditOutputRate(e.target.value)} className="budget-input" style={{ width: 90 }} />
                    </span>
                  </>
                ) : (
                  <>
                    <span className="col-cost">${m.input_rate_per_1k}</span>
                    <span className="col-cost">${m.output_rate_per_1k}</span>
                  </>
                )}
                <span className="col-tokens">{formatTokens(m.total_input_tokens)}</span>
                <span className="col-tokens">{formatTokens(m.total_output_tokens)}</span>
                <span className="col-cost">{formatCost(m.total_cost_usd)}</span>
                <span>
                  {editingModel === m.model ? (
                    <span style={{ display: 'flex', gap: 6 }}>
                      <button className="refresh-btn" style={{ padding: '6px 12px', fontSize: 12 }} onClick={() => handleSaveRate(m.model)} disabled={savingRate}>
                        <Save size={14} /> Save
                      </button>
                      <button className="refresh-btn" style={{ padding: '6px 12px', fontSize: 12, background: '#6b7280' }} onClick={cancelEditing}>
                        <XCircle size={14} />
                      </button>
                    </span>
                  ) : (
                    <button className="refresh-btn" style={{ padding: '6px 12px', fontSize: 12 }} onClick={() => startEditing(m)}>
                      <Edit3 size={14} /> Edit
                    </button>
                  )}
                </span>
              </div>
            ))}
            {/* Pagination footer — Prev / page indicator / Next.
                Buttons are disabled at the boundaries to make the
                affordance obvious without needing the user to click
                and bounce. Page indicator clicks are intentionally
                NOT supported (numbered pagination would be overkill
                for a list of ~25 models). */}
            {pricingTotalPages > 1 && (
              <div
                className="token-table-row"
                style={{
                  gridTemplateColumns: '1fr',
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '12px 16px',
                  background: '#f9fafb',
                  borderTop: '1px solid #e5e7eb',
                }}
              >
                <button
                  className="refresh-btn"
                  style={{ padding: '6px 14px', fontSize: 12, background: safePricingPage === 1 ? '#9ca3af' : undefined }}
                  onClick={() => setPricingPage((p) => Math.max(1, p - 1))}
                  disabled={safePricingPage === 1}
                >
                  <ChevronUp size={14} style={{ transform: 'rotate(-90deg)' }} /> Previous
                </button>
                <span style={{ fontSize: 13, color: '#374151', fontWeight: 500 }}>
                  Page {safePricingPage} of {pricingTotalPages}
                </span>
                <button
                  className="refresh-btn"
                  style={{ padding: '6px 14px', fontSize: 12, background: safePricingPage === pricingTotalPages ? '#9ca3af' : undefined }}
                  onClick={() => setPricingPage((p) => Math.min(pricingTotalPages, p + 1))}
                  disabled={safePricingPage === pricingTotalPages}
                >
                  Next <ChevronUp size={14} style={{ transform: 'rotate(90deg)' }} />
                </button>
              </div>
            )}
          </div>
        ) : (
          <div className="no-data" style={{ padding: 40 }}>
            <Cpu size={32} />
            <p>No pricing data available</p>
          </div>
        )}
      </div>
    </div>
  );
};

// =============================================================================
// AGENT PERFORMANCE TAB (with system avg response time)
// =============================================================================
const AgentPerformanceTab = ({ metricsData, loading, timePeriod, internalMetrics, usageData, usageLoading, kbStatsData, kbStatsLoading }) => {
  // Note: only the agent-metrics block is gated on `loading`. The
  // Conversation Threads block at the top has its own loading state
  // (via UsageBlock) so admins still see usage stats while the
  // /admin/metrics call is in flight (the latter can take a few
  // seconds in the cold-start case).
  const system = metricsData?.system || {};
  const agents = metricsData?.agents || {};
  const agentKeys = Object.keys(agents);

  // KB analytics — pulled from /api/kb-admin/stats (kb-lambda
  // admin_stats). Doc + chat stats refresh on the same period selector
  // as everything else on the page so admins see "what happened in the
  // last 24h / 7d / 30d" across both surfaces (AI Assistant + SFX Bot)
  // in one place.
  const kbDocs = kbStatsData?.documents || {};
  const kbChat = kbStatsData?.chat || {};
  const hasKbDocData =
    (kbDocs.processed || 0) > 0 ||
    (kbDocs.tokens || 0) > 0 ||
    (kbDocs.failed || 0) > 0;
  const hasKbChatData =
    (kbChat.sessions || 0) > 0 || (kbChat.messages || 0) > 0;

  const getAgentDisplayName = (name) => {
    const nameMap = {
      'gmail_agent': 'Email Service',
      'calendar_agent': 'Calendar Service',
      'docs_agent': 'Documents Service',
      'drive_agent': 'Storage Service',
      'sheets_agent': 'Spreadsheets Service',
      'mapping_agent': 'Data Mapping Service',
      'llm_tool': 'LLM Transform',
    };
    return nameMap[name] || name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  const getSuccessBadgeClass = (rate) => {
    if (rate >= 95) return 'success';
    if (rate >= 80) return 'pending';
    return 'error';
  };

  return (
    <div className="agent-performance-tab">
      {loading ? (
        <div className="token-tab-loading">
          <RefreshCw size={24} className="spin" />
          <span>Loading performance data...</span>
        </div>
      ) : (
        <>
      {/* System-wide Metrics */}
      <div className="stats-grid" style={{ marginBottom: 32 }}>
        <StatsCard
          icon={Zap}
          title="System Avg Response Time"
          value={formatMs(system.avg_response_time_ms)}
          subtitle="Time from user input to system reply"
        />
        <StatsCard
          icon={Activity}
          title="Total Requests (Period)"
          value={(system.total_requests || 0).toLocaleString()}
          subtitle={`Period: ${timePeriod}`}
        />
      </div>

      {/* Per-agent Cards */}
      <div className="services-header">
        <h2>Agent Performance</h2>
        <p>Per-agent metrics for the selected time period</p>
      </div>
      <div className="agents-grid">
        {agentKeys.length > 0 ? (
          agentKeys.map((name) => {
            const a = agents[name];
            const successRate = a.success_rate || 0;
            const badgeClass = getSuccessBadgeClass(successRate);
            return (
              <div key={name} className="agent-card">
                <div className="agent-card-header">
                  <div className="agent-info">
                    <div>
                      <h3 className="agent-name">{getAgentDisplayName(name)}</h3>
                      <p className="agent-description">{name}</p>
                    </div>
                  </div>
                </div>
                <div className="agent-stats" style={{ borderTop: 'none', paddingTop: 0 }}>
                  <div className="stat">
                    <span className={`stat-value log-status-icon ${badgeClass}`}>{successRate.toFixed(1)}%</span>
                    <span className="stat-label">Success Rate</span>
                  </div>
                  <div className="stat">
                    <span className="stat-value">{formatMs(a.avg_response_time_ms)}</span>
                    <span className="stat-label">Avg Response</span>
                  </div>
                  <div className="stat">
                    <span className="stat-value">{(a.total_actions || 0).toLocaleString()}</span>
                    <span className="stat-label">Total Actions</span>
                  </div>
                  <div className="stat">
                    <span className="stat-value" style={{ color: (a.failed_actions || 0) > 0 ? '#ef4444' : undefined }}>
                      {a.failed_actions || 0}
                    </span>
                    <span className="stat-label">Failed</span>
                  </div>
                </div>
              </div>
            );
          })
        ) : (
          <div className="no-data">
            <Server size={48} />
            <p>No agent data for this period</p>
            <span>Metrics will appear here once services start processing tasks</span>
          </div>
        )}
      </div>

      {/* Internal Components */}
      {internalMetrics && (
        <>
          <div className="services-header" style={{ marginTop: 40 }}>
            <h2>Internal Components</h2>
            <p>Supervisor and conversational layer LLM metrics</p>
          </div>
          <div className="agents-grid">
            {[
              { key: 'conversational', label: 'Conversational Agent', desc: 'Intent analysis, classification, formatting, memory' },
              { key: 'supervisor', label: 'Supervisor / Orchestrator', desc: 'Tool filtering, plan generation, LLM transforms' },
            ].map(({ key, label, desc }) => {
              const d = internalMetrics[key] || {};
              const rate = d.success_rate || 0;
              const badgeClass = getSuccessBadgeClass(rate);
              return (
                <div key={key} className="agent-card">
                  <div className="agent-card-header">
                    <div className="agent-info">
                      <div>
                        <h3 className="agent-name">{label}</h3>
                        <p className="agent-description">{desc}</p>
                      </div>
                    </div>
                  </div>
                  <div className="agent-stats" style={{ borderTop: 'none', paddingTop: 0 }}>
                    <div className="stat">
                      <span className={`stat-value log-status-icon ${badgeClass}`}>{rate.toFixed(1)}%</span>
                      <span className="stat-label">Success Rate</span>
                    </div>
                    <div className="stat">
                      <span className="stat-value">{formatMs(d.avg_duration_ms)}</span>
                      <span className="stat-label">Avg Latency</span>
                    </div>
                    <div className="stat">
                      <span className="stat-value">{(d.total_calls || 0).toLocaleString()}</span>
                      <span className="stat-label">LLM Calls</span>
                    </div>
                    <div className="stat">
                      <span className="stat-value" style={{ color: (d.failed_calls || 0) > 0 ? '#ef4444' : undefined }}>
                        {d.failed_calls || 0}
                      </span>
                      <span className="stat-label">Failed</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* ── Knowledge-base analytics ────────────────────────────────
            Document + chat performance for the SFX Bot side of the
            stack.  Token + cost numbers ALSO appear (de-duped) on the
            Token & Cost tab via the UsageLogs merge in
            dynamodb_log_storage.get_token_usage_stats.  Sourced from
            kb-lambda's /api/kb-admin/stats endpoint.  Two separate
            cards (one per surface) so admins can read each story
            without one drowning the other. */}
      <div className="services-header" style={{ marginTop: 40 }}>
        <h2><FileText size={20} /> Document Analytics</h2>
        <p>PDF ingestion + parse activity for the knowledge base ({PERIOD_LABELS[timePeriod] || timePeriod})</p>
      </div>
      {kbStatsLoading ? (
        <div className="token-tab-loading">
          <RefreshCw size={24} className="spin" />
          <span>Loading document analytics...</span>
        </div>
      ) : hasKbDocData ? (
        <div className="stats-grid" style={{ marginBottom: 32 }}>
          <StatsCard
            icon={FileText}
            title="Documents Processed"
            value={(kbDocs.processed || 0).toLocaleString()}
            subtitle={`${kbDocs.successful || 0} succeeded, ${kbDocs.failed || 0} failed`}
          />
          <StatsCard
            icon={BarChart3}
            title="Chunks Created"
            value={(kbDocs.chunks_created || 0).toLocaleString()}
            subtitle="Indexed in Weaviate"
          />
          <StatsCard
            icon={Zap}
            title="Ingestion Tokens"
            value={formatTokens(kbDocs.tokens || 0)}
            subtitle={`Cost: ${formatCost(kbDocs.cost_usd || 0)}`}
          />
          <StatsCard
            icon={Clock}
            title="Avg Parse Time"
            value={formatMs(kbDocs.avg_processing_time_ms)}
            subtitle={`Success rate: ${(kbDocs.success_rate || 0).toFixed(1)}%`}
          />
        </div>
      ) : (
        <div className="no-data" style={{ marginBottom: 32 }}>
          <FileText size={48} />
          <p>No document ingestion in this period</p>
          <span>Stats appear once admins upload PDFs to the knowledge base</span>
        </div>
      )}

      <div className="services-header">
        <h2><Bot size={20} /> SFX Bot Chat Analytics</h2>
        <p>End-user RAG chat activity ({PERIOD_LABELS[timePeriod] || timePeriod})</p>
      </div>
      {kbStatsLoading ? (
        <div className="token-tab-loading">
          <RefreshCw size={24} className="spin" />
          <span>Loading chat analytics...</span>
        </div>
      ) : hasKbChatData ? (
        <div className="stats-grid">
          <StatsCard
            icon={MessageSquare}
            title="Chat Sessions"
            value={(kbChat.sessions || 0).toLocaleString()}
            subtitle="Distinct conversations"
          />
          <StatsCard
            icon={Activity}
            title="Messages Exchanged"
            value={(kbChat.messages || 0).toLocaleString()}
            subtitle={
              kbChat.sessions
                ? `${(kbChat.messages / kbChat.sessions).toFixed(1)} avg per session`
                : 'Across all sessions'
            }
          />
          <StatsCard
            icon={Zap}
            title="Chat Tokens"
            value={formatTokens(kbChat.tokens || 0)}
            subtitle={`Cost: ${formatCost(kbChat.cost_usd || 0)}`}
          />
          <StatsCard
            icon={Clock}
            title="Avg Response Time"
            value={formatMs(kbChat.avg_response_time_ms)}
            subtitle="Per assistant reply"
          />
        </div>
      ) : (
        <div className="no-data">
          <Bot size={48} />
          <p>No SFX Bot chat activity in this period</p>
          <span>Stats appear once users start asking questions of the bot</span>
        </div>
      )}

      {/* ── AI Assistant Analytics ──────────────────────────────────
            Conversation-thread + request totals from the AI Assistant
            (supervisor-agent) surface. Placed AFTER "SFX Bot Chat
            Analytics" so the two end-user chat surfaces sit side by
            side at the bottom — Document Analytics (KB ingestion) →
            SFX Bot Chat (KB end-user) → AI Assistant Analytics
            (supervisor end-user).  Driven by the same `timePeriod`
            selector at the top of the page; see UsageBlock for the
            period-key mapping and the 1h fallback. */}
      <UsageBlock usageData={usageData} loading={usageLoading} timePeriod={timePeriod} />
        </>
      )}
    </div>
  );
};

// =============================================================================
// MAIN LOGS PAGE COMPONENT
// =============================================================================
const LogsPage = () => {
  // Default tab is 'performance' now: the standalone "Usage" tab was
  // merged into Performance per Sun-3-May feedback (its only content
  // — the Today/Week/Month conversation+request KPIs — felt sparse on
  // its own).  Backfill compatibility: any 'usage' value loaded from
  // session/localStorage by future code should be normalised to
  // 'performance' here, but right now activeTab lives only in
  // component state so the initial value is the only source.
  const [activeTab, setActiveTab] = useState('performance');
  const [timePeriod, setTimePeriod] = useState('24h');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);

  // Data states
  const [usageData, setUsageData] = useState(null);
  const [tokenData, setTokenData] = useState(null);
  const [tokenLoading, setTokenLoading] = useState(false);
  const [pricingData, setPricingData] = useState(null);
  const [budgetData, setBudgetData] = useState(null);
  const [metricsData, setMetricsData] = useState(null);
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [internalMetrics, setInternalMetrics] = useState(null);
  // Knowledge-base stats — drives the "Document Analytics" + "SFX Bot Chat
  // Analytics" sections inside the Performance tab.  Data shape matches
  // kb-lambda/functions/admin_stats.get_combined_stats_handler:
  //   { period, documents: {processed,chunks_created,tokens,cost_usd,
  //       success_rate,successful,failed,avg_processing_time_ms},
  //     chat:      {sessions,messages,tokens,cost_usd,
  //       avg_response_time_ms},
  //     totals:    {tokens,cost_usd} }
  // Token+cost numbers ALSO appear (de-duped via the UsageLogs merge in
  // dynamodb_log_storage.get_token_usage_stats) on the Token & Cost tab,
  // so the two surfaces tell the same story from different angles:
  // Performance = "what's the KB doing", Token & Cost = "what does it
  // cost in dollars across every model and tier".
  const [kbStatsData, setKbStatsData] = useState(null);
  const [kbStatsLoading, setKbStatsLoading] = useState(false);

  // Welcome line in the page header. Mirrors the pattern from
  // Dashboard.jsx (the existing user-facing landing page) so the
  // admin lands on a familiar greeting instead of a generic
  // "Usage, costs, and agent performance for your AI assistant"
  // subtitle that misrepresented the page (it covers KB ingestion +
  // SFX Bot chat too, not just the AI Assistant). Falls back to
  // "Admin" if localStorage.user is unparseable so the header
  // never renders an empty span.
  const [welcomeUser, setWelcomeUser] = useState({
    name: 'Admin',
    lastLogin: new Date().toLocaleString('en-US', {
      month: 'long', day: 'numeric', hour: 'numeric', minute: '2-digit', hour12: true,
    }),
  });

  useEffect(() => {
    try {
      const storedUser = localStorage.getItem('user');
      if (!storedUser) return;
      const userData = JSON.parse(storedUser);
      // Priority match Dashboard.jsx: full Google `name` (first +
      // middle), then `first_name`, then `username`. Two-word
      // truncation so admins with long names don't blow out the
      // header layout.
      let displayName = 'Admin';
      if (userData.name) {
        const parts = userData.name.trim().split(/\s+/);
        displayName = parts.length >= 2 ? `${parts[0]} ${parts[1]}` : parts[0];
      } else if (userData.first_name) {
        displayName = userData.first_name;
      } else if (userData.username) {
        displayName = userData.username;
      }
      setWelcomeUser((prev) => ({ ...prev, name: displayName }));
    } catch (err) {
      console.error('Error loading user info for LogsPage header:', err);
    }
  }, []);

  // refreshIntervalRef used to drive a 30s polling loop here. Removed
  // Sun-3-May per user feedback: "It keeps on reloading or something"
  // — the silent refresh every 30 seconds rerendered the KPI tiles,
  // re-paged the pricing table, and made the page feel jittery.
  // Refresh is now manual only via the header button (which is always
  // available + shows a spinning icon while in flight).

  // ── Data fetching ──

  const fetchUsageSummary = useCallback(async () => {
    try {
      const res = await supervisorApi.get('/admin/usage/summary');
      setUsageData(res.data);
    } catch (err) {
      console.error('Error fetching usage summary:', err.response?.status, err);
    }
  }, []);

  const fetchTokenStats = useCallback(async () => {
    setTokenLoading(true);
    try {
      const res = await supervisorApi.get('/logs/stats', { params: { period: timePeriod } });
      setTokenData(res.data);
    } catch (err) {
      console.error('Error fetching token stats:', err.response?.status, err);
    } finally {
      setTokenLoading(false);
    }
  }, [timePeriod]);

  const fetchPricing = useCallback(async () => {
    try {
      const res = await supervisorApi.get('/admin/pricing');
      setPricingData(res.data);
    } catch (err) {
      console.error('Error fetching pricing:', err.response?.status, err.response?.data ?? err);
    }
  }, []);

  const fetchBudget = useCallback(async () => {
    try {
      const res = await supervisorApi.get('/admin/settings/budget');
      setBudgetData(res.data);
    } catch (err) {
      console.error('Error fetching budget:', err.response?.status, err);
    }
  }, []);

  const fetchMetrics = useCallback(async () => {
    setMetricsLoading(true);
    try {
      const res = await supervisorApi.get('/admin/metrics', { params: { period: timePeriod } });
      setMetricsData(res.data);
    } catch (err) {
      console.error('Error fetching metrics:', err.response?.status, err);
    } finally {
      setMetricsLoading(false);
    }
  }, [timePeriod]);

  const fetchInternalMetrics = useCallback(async () => {
    try {
      const res = await supervisorApi.get('/admin/metrics/internal', { params: { period: timePeriod } });
      setInternalMetrics(res.data);
    } catch (err) {
      console.error('Error fetching internal metrics:', err.response?.status, err);
    }
  }, [timePeriod]);

  // KB admin stats — separate API gateway (kbApi) because the
  // knowledge-base service has its own gateway. Failure to fetch is
  // non-fatal: the Performance tab degrades gracefully to "no KB data
  // for this period" rather than blocking the supervisor sections.
  const fetchKbStats = useCallback(async () => {
    setKbStatsLoading(true);
    try {
      const res = await kbApi.get('/api/kb-admin/stats', { params: { period: timePeriod } });
      setKbStatsData(res.data);
    } catch (err) {
      console.error('Error fetching KB admin stats:', err.response?.status, err);
      setKbStatsData(null);
    } finally {
      setKbStatsLoading(false);
    }
  }, [timePeriod]);

  // ── Save handlers ──

  const handleSaveRate = async (model, inputRate, outputRate) => {
    try {
      await supervisorApi.put(`/admin/pricing/${encodeURIComponent(model)}`, {
        input_rate_per_1k: inputRate,
        output_rate_per_1k: outputRate,
      });
      await fetchPricing();
    } catch (err) {
      console.error('Error saving rate:', err.response?.status, err.response?.data ?? err);
      setError('Failed to save pricing. Please try again.');
    }
  };

  // The budget save handler used to live here; it moved to
  // QuotaPage.jsx along with the editor on 2026-05-04. We still
  // fetch the budget here so the BudgetBanner at the top of the
  // Token & Cost tab can render warn/over-budget states — admins
  // landing on the Admin Dashboard see the same alert UI as on the
  // Token Management page without an extra navigation step.

  // ── Refresh all ──

  const refreshAllData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await Promise.all([
        fetchUsageSummary(),
        fetchTokenStats(),
        fetchPricing(),
        fetchBudget(),
        fetchMetrics(),
        fetchInternalMetrics(),
        fetchKbStats(),
      ]);
      setError(null);
    } catch (err) {
      console.error('Error refreshing data:', err);
      setError('Failed to refresh data. Please try again.');
    } finally {
      setIsRefreshing(false);
      setLoading(false);
    }
  }, [fetchUsageSummary, fetchTokenStats, fetchPricing, fetchBudget, fetchMetrics, fetchInternalMetrics, fetchKbStats]);

  // ── Effects ──

  // Initial load only. We deliberately disable the eslint deps warning
  // here: `refreshAllData` IS in the dependency array, but it is wrapped
  // in useCallback whose deps include `timePeriod` (via fetchTokenStats /
  // fetchMetrics / fetchInternalMetrics). If we let this effect re-run on
  // `refreshAllData` change, every time the user picks a new period the
  // page would also re-fetch the period-INVARIANT calls (usage summary,
  // pricing, budget) which is wasteful — the second useEffect below
  // already handles the period-DEPENDENT refetch. So we mount-once.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { refreshAllData(); }, []);

  useEffect(() => {
    fetchTokenStats();
    fetchMetrics();
    fetchInternalMetrics();
    fetchKbStats();
  }, [timePeriod, fetchTokenStats, fetchMetrics, fetchInternalMetrics, fetchKbStats]);

  // ── Render ──

  if (loading) {
    return (
      <div className="logs-page">
        <div className="loading-container">
          <RefreshCw className="loading-spinner" size={32} />
          <p>Loading admin dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="logs-page">
      {/* Page Header */}
      <div className="logs-header">
        <div className="header-content">
          <h1>
            <Shield size={28} />
            Admin Dashboard
          </h1>
          {/* Welcome line replaces the old "Usage, costs, and agent
              performance for your AI assistant" subtitle (which
              misdescribed the page — it covers KB ingestion + SFX
              Bot chat in addition to the AI Assistant). Mirrors the
              Dashboard.jsx welcome-title pattern so admins land on
              a familiar greeting. The strong tags inherit
              header-subtitle's color but render bold, matching the
              Dashboard.jsx Last Login line exactly. */}
          <p className="header-subtitle logs-welcome-line">
            Welcome, <strong>{welcomeUser.name}</strong>
          </p>
          <p className="header-subtitle logs-last-login">
            Last Login: <strong>{welcomeUser.lastLogin}</strong>
          </p>
        </div>
        <div className="header-actions">
          <TimePeriodSelector
            selectedPeriod={timePeriod}
            onPeriodChange={setTimePeriod}
          />
          <button
            className={`refresh-btn ${isRefreshing ? 'refreshing' : ''}`}
            onClick={refreshAllData}
            disabled={isRefreshing}
          >
            <RefreshCw size={18} className={isRefreshing ? 'spin' : ''} />
            {isRefreshing ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="error-banner">
          <AlertCircle size={20} />
          <span>{error}</span>
          <button onClick={() => setError(null)}><XCircle size={16} /></button>
        </div>
      )}

      {/* Tabs.  Sun-3-May restructure: the standalone "Usage" tab was
          merged into "Agent Performance" (now the default).  Two tabs
          are clearer than three when the third one only shows 6
          KPIs. */}
      <div className="tabs-container">
        <div className="tabs">
          <button className={`tab ${activeTab === 'performance' ? 'active' : ''}`} onClick={() => setActiveTab('performance')}>
            <Activity size={18} />
            Performance
          </button>
          <button className={`tab ${activeTab === 'tokens' ? 'active' : ''}`} onClick={() => setActiveTab('tokens')}>
            <DollarSign size={18} />
            Token &amp; Cost
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {activeTab === 'tokens' && (
          <TokenCostTab
            tokenData={tokenData}
            tokenLoading={tokenLoading}
            pricingData={pricingData}
            budgetData={budgetData}
            onSaveRate={handleSaveRate}
          />
        )}

        {activeTab === 'performance' && (
          <AgentPerformanceTab
            metricsData={metricsData}
            loading={metricsLoading}
            timePeriod={timePeriod}
            internalMetrics={internalMetrics}
            usageData={usageData}
            usageLoading={!usageData && loading}
            kbStatsData={kbStatsData}
            kbStatsLoading={kbStatsLoading}
          />
        )}
      </div>
    </div>
  );
};

export default LogsPage;
