import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  Activity, Clock, CheckCircle, XCircle, AlertTriangle, RefreshCw,
  TrendingUp, TrendingDown, Server, Zap, BarChart3,
  Shield, DollarSign, Cpu, Edit3, Save, Calendar, AlertCircle,
  Search, ChevronUp
} from 'lucide-react';
import '../css/LogsPage.css';
import { supervisorApi } from '../api';

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
// USAGE TAB — Aggregated conversation/request counts
// =============================================================================
// Block of conversation-thread + request totals shown at the top of
// the Performance tab.  Renamed from "Conversations" to "Conversation
// Threads" because admins were reading "conversation" as a single
// turn — but each row counts a UNIQUE thread_id (one user back-and-
// forth = one thread regardless of how many messages it contains),
// which is what the metric represents.
//
// The block stays as 3 fixed rolling windows (24h / 7d / 30d) on
// purpose: those are operational SLOs (how many threads ran in the
// last day vs. the last week) and admins want to compare them at a
// glance.  The period selector at the top of the Admin Dashboard
// drives the agent metrics BELOW this block, not these tiles — that
// distinction is called out in the section subtitle so the user
// doesn't expect the dropdown to change these numbers.
const UsageBlock = ({ usageData, loading }) => {
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

  const periods = [
    { key: 'today',      label: 'Today (24h)',     icon: Clock },
    { key: 'this_week',  label: 'This Week (7d)',  icon: Calendar },
    { key: 'this_month', label: 'This Month (30d)', icon: BarChart3 },
  ];

  return (
    <div className="usage-block">
      <div className="services-header">
        <h2><BarChart3 size={20} /> Conversation Threads &amp; Requests</h2>
        <p>
          Rolling totals across the last 24 hours, 7 days, and 30 days.
          {' '}
          <em style={{ color: '#94a3b8' }}>
            (Independent of the period selector at the top &mdash; that
            drives the agent metrics below.)
          </em>
        </p>
      </div>
      <div className="stats-grid" style={{ marginBottom: 32 }}>
        {periods.map(p => {
          const d = usageData[p.key] || {};
          return (
            <React.Fragment key={p.key}>
              <StatsCard
                icon={p.icon}
                title={`Conversation Threads \u2014 ${p.label}`}
                value={(d.conversations || 0).toLocaleString()}
                subtitle="Unique threads (each is one user back-and-forth)"
              />
              <StatsCard
                icon={Zap}
                title={`Requests \u2014 ${p.label}`}
                value={(d.requests || 0).toLocaleString()}
                subtitle="Total user messages processed"
              />
            </React.Fragment>
          );
        })}
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
const TokenCostTab = ({ tokenData, tokenLoading, pricingData, budgetData, onSaveRate, onSaveBudget }) => {
  const [editingModel, setEditingModel] = useState(null);
  const [editInputRate, setEditInputRate] = useState('');
  const [editOutputRate, setEditOutputRate] = useState('');
  const [budgetInput, setBudgetInput] = useState('');
  const [thresholdInput, setThresholdInput] = useState('');
  const [savingRate, setSavingRate] = useState(false);
  const [savingBudget, setSavingBudget] = useState(false);
  // Model pricing table — search + pagination. The full pricing
  // table now spans 20+ models (gpt-4 / gpt-4o / gpt-4.1 / gpt-5.x /
  // o1 / o3 / o4 families) so a single scroll-forever list became
  // unusable. Search is applied first (case-insensitive substring
  // on the model name), then the result is sliced by page.
  const [pricingSearch, setPricingSearch] = useState('');
  const [pricingPage, setPricingPage] = useState(1);
  const PRICING_PAGE_SIZE = 8;

  useEffect(() => {
    if (budgetData) {
      if (budgetData.monthly_budget_usd != null) setBudgetInput(String(budgetData.monthly_budget_usd));
      if (budgetData.alert_threshold_pct != null) setThresholdInput(String(budgetData.alert_threshold_pct));
    }
  }, [budgetData]);

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

  const handleSaveBudget = async () => {
    const body = {};
    const b = parseFloat(budgetInput);
    const t = parseFloat(thresholdInput);
    if (!isNaN(b)) body.monthly_budget_usd = b;
    if (!isNaN(t)) body.alert_threshold_pct = t;
    setSavingBudget(true);
    await onSaveBudget(body);
    setSavingBudget(false);
  };

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

  const pricingTotalPages = Math.max(1, Math.ceil(filteredModels.length / PRICING_PAGE_SIZE));
  // Clamp current page when filter shrinks the list below the current page.
  const safePricingPage = Math.min(pricingPage, pricingTotalPages);
  const pricingPageStart = (safePricingPage - 1) * PRICING_PAGE_SIZE;
  const pagedModels = filteredModels.slice(pricingPageStart, pricingPageStart + PRICING_PAGE_SIZE);

  return (
    <div className="token-usage-tab">
      {/* Budget Banner */}
      <BudgetBanner budget={budgetData} />

      {/* Budget Controls */}
      <div className="token-section">
        <h2><DollarSign size={20} /> Monthly Budget</h2>
        <div className="budget-controls">
          <div className="budget-field">
            <label>Monthly Budget (USD)</label>
            <input
              type="number"
              min="0"
              step="0.01"
              value={budgetInput}
              onChange={(e) => setBudgetInput(e.target.value)}
              placeholder="e.g. 50.00"
              className="budget-input"
            />
          </div>
          <div className="budget-field">
            <label>Alert Threshold (%)</label>
            <input
              type="number"
              min="0"
              max="100"
              step="1"
              value={thresholdInput}
              onChange={(e) => setThresholdInput(e.target.value)}
              placeholder="80"
              className="budget-input"
            />
          </div>
          <button
            className="refresh-btn"
            onClick={handleSaveBudget}
            disabled={savingBudget}
            style={{ alignSelf: 'flex-end' }}
          >
            <Save size={16} />
            {savingBudget ? 'Saving...' : 'Save Budget'}
          </button>
          <div className="budget-spend">
            <span className="budget-spend-label">Current Month Spend</span>
            <span className="budget-spend-value">{formatCost(budgetData?.current_month_cost_usd)}</span>
          </div>
        </div>
      </div>

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
            <StatsCard icon={DollarSign} title="Estimated Cost" value={formatCost(totals.total_cost_usd)} subtitle="Based on model pricing" />
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
const AgentPerformanceTab = ({ metricsData, loading, timePeriod, internalMetrics, usageData, usageLoading }) => {
  // Note: only the agent-metrics block is gated on `loading`. The
  // Conversation Threads block at the top has its own loading state
  // (via UsageBlock) so admins still see usage stats while the
  // /admin/metrics call is in flight (the latter can take a few
  // seconds in the cold-start case).
  const system = metricsData?.system || {};
  const agents = metricsData?.agents || {};
  const agentKeys = Object.keys(agents);

  const formatMs = (ms) => {
    if (ms == null || ms === 0) return 'N/A';
    if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
    return `${Math.round(ms)}ms`;
  };

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
      {/* ── Usage block (the standalone "Usage" tab used to live here).
            Promoted to the top of Performance per Sun-3-May feedback:
            "nothing but usage is in the USAGE page" — having it as its
            own tab created a click + an empty-feeling page.  The block
            uses fixed rolling windows (Today / Week / Month) and
            ignores the period selector on purpose, see UsageBlock for
            rationale. */}
      <UsageBlock usageData={usageData} loading={usageLoading} />

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

  const refreshIntervalRef = useRef(null);

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

  const handleSaveBudget = async (body) => {
    try {
      const res = await supervisorApi.put('/admin/settings/budget', body);
      setBudgetData(res.data);
    } catch (err) {
      console.error('Error saving budget:', err.response?.status, err.response?.data ?? err);
      setError('Failed to save budget. Please try again.');
    }
  };

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
      ]);
      setError(null);
    } catch (err) {
      console.error('Error refreshing data:', err);
      setError('Failed to refresh data. Please try again.');
    } finally {
      setIsRefreshing(false);
      setLoading(false);
    }
  }, [fetchUsageSummary, fetchTokenStats, fetchPricing, fetchBudget, fetchMetrics, fetchInternalMetrics]);

  // ── Effects ──

  useEffect(() => {
    refreshAllData();
    refreshIntervalRef.current = setInterval(refreshAllData, 30000);
    return () => {
      if (refreshIntervalRef.current) clearInterval(refreshIntervalRef.current);
    };
  }, [refreshAllData]);

  useEffect(() => {
    fetchTokenStats();
    fetchMetrics();
    fetchInternalMetrics();
  }, [timePeriod, fetchTokenStats, fetchMetrics, fetchInternalMetrics]);

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
          <p className="header-subtitle">
            Usage, costs, and agent performance for your AI assistant
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
            onSaveBudget={handleSaveBudget}
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
          />
        )}
      </div>
    </div>
  );
};

export default LogsPage;
