import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Activity, Clock, CheckCircle, XCircle, AlertTriangle, RefreshCw,
  TrendingUp, TrendingDown, Server, Zap, BarChart3,
  Shield, DollarSign, Cpu, Edit3, Save, Calendar, AlertCircle
} from 'lucide-react';
import '../css/LogsPage.css';

const API_BASE_URL = 'http://localhost:8010';

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
const UsageTab = ({ usageData, loading }) => {
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
    { key: 'today', label: 'Today (24h)', icon: Clock },
    { key: 'this_week', label: 'This Week (7d)', icon: Calendar },
    { key: 'this_month', label: 'This Month (30d)', icon: BarChart3 },
  ];

  return (
    <div className="usage-tab">
      <div className="stats-grid">
        {periods.map(p => {
          const d = usageData[p.key] || {};
          return (
            <React.Fragment key={p.key}>
              <StatsCard
                icon={p.icon}
                title={`Conversations — ${p.label}`}
                value={(d.conversations || 0).toLocaleString()}
                subtitle="Unique conversations"
              />
              <StatsCard
                icon={Zap}
                title={`Requests — ${p.label}`}
                value={(d.requests || 0).toLocaleString()}
                subtitle="Total requests processed"
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
      '0.5': 'Quick Check (0.5)',
      '1': 'Full Analysis (1)',
      'classifier': 'Agent Classifier',
      'supervisor': 'Plan Generation',
      'formatter': 'Confirmation Fmt',
      'memory': 'Memory',
      'post': 'Post-Processing',
      'enrichment': 'Enrichment'
    };
    return labels[tier] || tier || 'Other';
  };

  const models = pricingData?.models || [];

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
        {models.length > 0 ? (
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
            {models.map((m) => (
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
const AgentPerformanceTab = ({ metricsData, loading, timePeriod }) => {
  if (loading) {
    return (
      <div className="token-tab-loading">
        <RefreshCw size={24} className="spin" />
        <span>Loading performance data...</span>
      </div>
    );
  }

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
      'gdocs_agent': 'Documents Service',
      'gdrive_agent': 'Storage Service',
      'sheets_agent': 'Spreadsheets Service',
      'supervisor_agent': 'Central Coordinator',
      'mapping_agent': 'Data Mapping Service'
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
    </div>
  );
};

// =============================================================================
// MAIN LOGS PAGE COMPONENT
// =============================================================================
const LogsPage = () => {
  const [activeTab, setActiveTab] = useState('usage');
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

  const refreshIntervalRef = useRef(null);

  // ── Data fetching ──

  const fetchUsageSummary = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/admin/usage/summary`);
      if (res.ok) setUsageData(await res.json());
    } catch (err) {
      console.error('Error fetching usage summary:', err);
    }
  }, []);

  const fetchTokenStats = useCallback(async () => {
    setTokenLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/logs/stats?period=${timePeriod}`);
      if (res.ok) setTokenData(await res.json());
    } catch (err) {
      console.error('Error fetching token stats:', err);
    } finally {
      setTokenLoading(false);
    }
  }, [timePeriod]);

  const fetchPricing = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/admin/pricing`);
      if (res.ok) {
        setPricingData(await res.json());
      } else {
        console.error('Pricing endpoint returned', res.status, await res.text().catch(() => ''));
      }
    } catch (err) {
      console.error('Error fetching pricing:', err);
    }
  }, []);

  const fetchBudget = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/admin/settings/budget`);
      if (res.ok) setBudgetData(await res.json());
    } catch (err) {
      console.error('Error fetching budget:', err);
    }
  }, []);

  const fetchMetrics = useCallback(async () => {
    setMetricsLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/admin/metrics?period=${timePeriod}`);
      if (res.ok) setMetricsData(await res.json());
    } catch (err) {
      console.error('Error fetching metrics:', err);
    } finally {
      setMetricsLoading(false);
    }
  }, [timePeriod]);

  // ── Save handlers ──

  const handleSaveRate = async (model, inputRate, outputRate) => {
    try {
      const res = await fetch(`${API_BASE_URL}/admin/pricing/${encodeURIComponent(model)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ input_rate_per_1k: inputRate, output_rate_per_1k: outputRate })
      });
      if (!res.ok) throw new Error(await res.text());
      await fetchPricing();
    } catch (err) {
      console.error('Error saving rate:', err);
      setError('Failed to save pricing. Please try again.');
    }
  };

  const handleSaveBudget = async (body) => {
    try {
      const res = await fetch(`${API_BASE_URL}/admin/settings/budget`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setBudgetData(data);
    } catch (err) {
      console.error('Error saving budget:', err);
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
      ]);
      setError(null);
    } catch (err) {
      console.error('Error refreshing data:', err);
      setError('Failed to refresh data. Please try again.');
    } finally {
      setIsRefreshing(false);
      setLoading(false);
    }
  }, [fetchUsageSummary, fetchTokenStats, fetchPricing, fetchBudget, fetchMetrics]);

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
  }, [timePeriod, fetchTokenStats, fetchMetrics]);

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

      {/* Tabs */}
      <div className="tabs-container">
        <div className="tabs">
          <button className={`tab ${activeTab === 'usage' ? 'active' : ''}`} onClick={() => setActiveTab('usage')}>
            <BarChart3 size={18} />
            Usage
          </button>
          <button className={`tab ${activeTab === 'tokens' ? 'active' : ''}`} onClick={() => setActiveTab('tokens')}>
            <DollarSign size={18} />
            Token &amp; Cost
          </button>
          <button className={`tab ${activeTab === 'performance' ? 'active' : ''}`} onClick={() => setActiveTab('performance')}>
            <Activity size={18} />
            Agent Performance
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {activeTab === 'usage' && (
          <UsageTab usageData={usageData} loading={!usageData && loading} />
        )}

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
          />
        )}
      </div>
    </div>
  );
};

export default LogsPage;
