import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  Activity, Clock, CheckCircle, XCircle, AlertTriangle, RefreshCw,
  TrendingUp, TrendingDown, Server, Zap, Users, BarChart3, Eye,
  Filter, Search, ChevronDown, ChevronUp, AlertCircle, Bell, X,
  Shield, Database, Calendar, DollarSign, Cpu
} from 'lucide-react';
import '../css/LogsPage.css';

// API Base URL - using admin endpoints for privacy
const API_BASE_URL = 'http://localhost:8010';

// =============================================================================
// SYSTEM HEALTH INDICATOR COMPONENT
// =============================================================================
const SystemHealthBanner = ({ health, onDismiss }) => {
  if (!health) return null;
  
  const getHealthClass = () => {
    switch (health.indicator) {
      case '🟢': return 'health-banner health-good';
      case '🟡': return 'health-banner health-warning';
      case '🔴': return 'health-banner health-critical';
      default: return 'health-banner';
    }
  };

  const getHealthIcon = () => {
    switch (health.indicator) {
      case '🟢': return <CheckCircle size={20} />;
      case '🟡': return <AlertTriangle size={20} />;
      case '🔴': return <XCircle size={20} />;
      default: return <Activity size={20} />;
    }
  };

  return (
    <div className={getHealthClass()}>
      <div className="health-content">
        {getHealthIcon()}
        <span className="health-status">System Status: {health.status}</span>
        <div className="health-checks">
          {health.checks && (
            <>
              <span className="health-check">
                <Server size={14} /> 
                Agents: {health.checks.agents?.active || 0}/{health.checks.agents?.total || 0}
              </span>
              <span className="health-check">
                <Database size={14} /> 
                Database: {health.checks.database || 'Unknown'}
              </span>
              {health.checks.recent_errors > 0 && (
                <span className="health-check error">
                  <AlertCircle size={14} /> 
                  {health.checks.recent_errors} recent errors
                </span>
              )}
            </>
          )}
        </div>
      </div>
      {onDismiss && (
        <button className="health-dismiss" onClick={onDismiss}>
          <X size={16} />
        </button>
      )}
    </div>
  );
};

// =============================================================================
// ALERT BANNER COMPONENT
// =============================================================================
const AlertBanner = ({ alerts, onDismiss }) => {
  if (!alerts || alerts.length === 0) return null;

  const getSeverityClass = (severity) => {
    switch (severity) {
      case 'critical': return 'alert-critical';
      case 'warning': return 'alert-warning';
      default: return 'alert-info';
    }
  };

  const getSeverityIcon = (severity) => {
    switch (severity) {
      case 'critical': return <XCircle size={16} />;
      case 'warning': return <AlertTriangle size={16} />;
      default: return <AlertCircle size={16} />;
    }
  };

  return (
    <div className="alerts-container">
      <div className="alerts-header">
        <Bell size={18} />
        <span>Recent Alerts ({alerts.length})</span>
      </div>
      <div className="alerts-list">
        {alerts.slice(0, 5).map((alert, idx) => (
          <div key={idx} className={`alert-item ${getSeverityClass(alert.severity)}`}>
            {getSeverityIcon(alert.severity)}
            <div className="alert-content">
              <span className="alert-service">{alert.service}</span>
              <span className="alert-message">{alert.message}</span>
              <span className="alert-time">{alert.time_ago}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

// =============================================================================
// TIME PERIOD SELECTOR COMPONENT
// =============================================================================
const TimePeriodSelector = ({ selectedPeriod, onPeriodChange }) => {
  const periods = [
    { value: '1h', label: 'Last Hour' },
    { value: '6h', label: 'Last 6 Hours' },
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
// STATS CARD COMPONENT (Admin-Friendly)
// =============================================================================
const StatsCard = ({ icon: Icon, title, value, subtitle, trend, trendDirection }) => {
  return (
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
};

// =============================================================================
// AGENT PERFORMANCE CARD (Admin-Friendly Names)
// =============================================================================
const AgentPerformanceCard = ({ agent }) => {
  const getScoreColor = (score) => {
    if (score >= 80) return 'excellent';
    if (score >= 60) return 'good';
    if (score >= 40) return 'fair';
    return 'poor';
  };

  const getStatusIcon = (status) => {
    switch (status) {
      case 'operational': return <CheckCircle className="status-icon operational" size={16} />;
      case 'degraded': return <AlertTriangle className="status-icon degraded" size={16} />;
      case 'down': return <XCircle className="status-icon down" size={16} />;
      default: return <Activity className="status-icon" size={16} />;
    }
  };

  // Admin-friendly agent names
  const getAgentDisplayName = (agentName) => {
    const nameMap = {
      'gmail_agent': 'Email Service',
      'calendar_agent': 'Calendar Service',
      'gdocs_agent': 'Documents Service',
      'gdrive_agent': 'Storage Service',
      'sheets_agent': 'Spreadsheets Service',
      'supervisor_agent': 'Central Coordinator',
      'mapping_agent': 'Data Mapping Service'
    };
    return nameMap[agentName] || agentName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  };

  // Admin-friendly descriptions
  const getAgentDescription = (agentName) => {
    const descMap = {
      'gmail_agent': 'Handles email-related tasks',
      'calendar_agent': 'Manages calendar and scheduling',
      'gdocs_agent': 'Processes document operations',
      'gdrive_agent': 'Manages file storage and retrieval',
      'sheets_agent': 'Handles spreadsheet operations',
      'supervisor_agent': 'Coordinates all services',
      'mapping_agent': 'Maps data between formats'
    };
    return descMap[agentName] || 'Processes automated tasks';
  };

  const overallScore = agent.overall_score || 0;
  const scoreClass = getScoreColor(overallScore);

  return (
    <div className="agent-card">
      <div className="agent-card-header">
        <div className="agent-info">
          {getStatusIcon(agent.status || 'operational')}
          <div>
            <h3 className="agent-name">{getAgentDisplayName(agent.agent_name)}</h3>
            <p className="agent-description">{getAgentDescription(agent.agent_name)}</p>
          </div>
        </div>
        <div className={`overall-score ${scoreClass}`}>
          <span className="score-value">{overallScore.toFixed(0)}</span>
          <span className="score-label">Score</span>
        </div>
      </div>
      
      <div className="agent-metrics">
        <div className="metric">
          <span className="metric-label">Reliability</span>
          <div className="metric-bar">
            <div 
              className="metric-fill reliability" 
              style={{ width: `${agent.reliability || 0}%` }}
            />
          </div>
          <span className="metric-value">{(agent.reliability || 0).toFixed(0)}%</span>
        </div>
        
        <div className="metric">
          <span className="metric-label">Speed</span>
          <div className="metric-bar">
            <div 
              className="metric-fill speed" 
              style={{ width: `${agent.speed || 0}%` }}
            />
          </div>
          <span className="metric-value">{(agent.speed || 0).toFixed(0)}%</span>
        </div>
        
        <div className="metric">
          <span className="metric-label">Accuracy</span>
          <div className="metric-bar">
            <div 
              className="metric-fill accuracy" 
              style={{ width: `${agent.accuracy || 0}%` }}
            />
          </div>
          <span className="metric-value">{(agent.accuracy || 0).toFixed(0)}%</span>
        </div>
      </div>

      <div className="agent-stats">
        <div className="stat">
          <span className="stat-value">{agent.total_calls || 0}</span>
          <span className="stat-label">Total Tasks</span>
        </div>
        <div className="stat">
          <span className="stat-value">{agent.successful_calls || 0}</span>
          <span className="stat-label">Successful</span>
        </div>
        <div className="stat">
          <span className="stat-value">{agent.avg_response_time ? `${(agent.avg_response_time / 1000).toFixed(1)}s` : 'N/A'}</span>
          <span className="stat-label">Avg Time</span>
        </div>
      </div>
    </div>
  );
};

// =============================================================================
// ACTIVITY ENTRY COMPONENT (Privacy-Safe)
// =============================================================================
const ActivityEntry = ({ activity, expanded, onToggle }) => {
  const getStatusIcon = (status) => {
    if (status === 'success' || status === 'completed') {
      return <CheckCircle className="log-status-icon success" size={16} />;
    } else if (status === 'error' || status === 'failed') {
      return <XCircle className="log-status-icon error" size={16} />;
    } else if (status === 'pending' || status === 'processing') {
      return <Clock className="log-status-icon pending" size={16} />;
    }
    return <Activity className="log-status-icon" size={16} />;
  };

  const getServiceIcon = (service) => {
    const serviceIcons = {
      'Email Service': '📧',
      'Calendar Service': '📅',
      'Documents Service': '📄',
      'Storage Service': '📁',
      'Spreadsheets Service': '📊',
      'Central Coordinator': '🎯',
      'Data Mapping Service': '🔄'
    };
    return serviceIcons[service] || '⚙️';
  };

  return (
    <div className={`activity-entry ${activity.status}`}>
      <div className="activity-main" onClick={onToggle}>
        <div className="activity-icon">
          {getStatusIcon(activity.status)}
        </div>
        <div className="activity-content">
          <div className="activity-header">
            <span className="activity-service">
              {getServiceIcon(activity.service)} {activity.service}
            </span>
            <span className="activity-action">{activity.action}</span>
          </div>
          <p className="activity-description">{activity.description}</p>
          <div className="activity-meta">
            <span className="activity-time">
              <Clock size={12} /> {activity.time_ago}
            </span>
            {activity.duration && (
              <span className="activity-duration">
                <Zap size={12} /> {activity.duration}
              </span>
            )}
          </div>
        </div>
        <div className="activity-toggle">
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </div>
      </div>
      
      {expanded && activity.details && (
        <div className="activity-details">
          <div className="details-grid">
            {activity.details.task_id && (
              <div className="detail-item">
                <span className="detail-label">Task ID:</span>
                <span className="detail-value">{activity.details.task_id}</span>
              </div>
            )}
            {activity.details.confidence && (
              <div className="detail-item">
                <span className="detail-label">Confidence:</span>
                <span className="detail-value">{activity.details.confidence}</span>
              </div>
            )}
            {activity.details.items_processed && (
              <div className="detail-item">
                <span className="detail-label">Items Processed:</span>
                <span className="detail-value">{activity.details.items_processed}</span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

// =============================================================================
// TOKEN USAGE TAB COMPONENT
// =============================================================================
const TokenUsageTab = ({ tokenData, loading }) => {
  if (loading) {
    return (
      <div className="token-tab-loading">
        <RefreshCw size={24} className="spin" />
        <span>Loading token data...</span>
      </div>
    );
  }

  const summary = tokenData?.token_summary;
  const totals = summary?.totals || {};
  const byModel = summary?.by_model || [];
  const byTier = summary?.by_tier || [];
  const byOperation = summary?.by_operation || [];

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

  const maxTokens = byModel.reduce((m, r) => Math.max(m, r.tokens || 0), 1);

  const hasData = (totals.total_calls || 0) > 0;

  if (!hasData) {
    return (
      <div className="token-usage-tab">
        <div className="no-data">
          <DollarSign size={48} />
          <p>No token usage data yet</p>
          <span>Token consumption will appear here once the supervisor processes tasks</span>
        </div>
      </div>
    );
  }

  const getOperationLabel = (op) => {
    const labels = {
      'tier_1_full_analysis': 'Full Task Analysis',
      'tier_0.5_unified_check': 'Quick Intent Check',
      'confirmation_formatter': 'Confirmation Formatter',
      'agent_tool_classification': 'Agent/Tool Classifier',
      'plan_generation': 'Execution Plan Generation',
      'memory_summarization': 'Memory Summarization',
      'response_composer_safety_net': 'Response Safety Net',
      'content_enrichment': 'Content Enrichment'
    };
    return labels[op] || op?.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()) || 'Unknown';
  };

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

  return (
    <div className="token-usage-tab">
      {/* Stat cards */}
      <div className="stats-grid">
        <StatsCard
          icon={Cpu}
          title="Total LLM Calls"
          value={(totals.total_calls || 0).toLocaleString()}
          subtitle={`${totals.successful_calls || 0} succeeded, ${totals.failed_calls || 0} failed`}
        />
        <StatsCard
          icon={Zap}
          title="Total Tokens"
          value={formatTokens(totals.total_tokens)}
          subtitle={`In: ${formatTokens(totals.total_input_tokens)} / Out: ${formatTokens(totals.total_output_tokens)}`}
        />
        <StatsCard
          icon={DollarSign}
          title="Estimated Cost"
          value={formatCost(totals.total_cost_usd)}
          subtitle="Based on model pricing"
        />
        <StatsCard
          icon={Clock}
          title="Avg Latency"
          value={totals.avg_duration_ms ? `${(totals.avg_duration_ms / 1000).toFixed(2)}s` : 'N/A'}
          subtitle="Per LLM call"
        />
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
                <span className="col-model">
                  <Cpu size={14} />
                  {row.model}
                </span>
                <span className="col-calls">{row.calls}</span>
                <span className="col-tokens">{formatTokens(row.input_tokens)}</span>
                <span className="col-tokens">{formatTokens(row.output_tokens)}</span>
                <span className="col-tokens">{formatTokens(row.tokens)}</span>
                <span className="col-cost">{formatCost(row.cost_usd)}</span>
                <span className="col-bar">
                  <div className="token-bar-track">
                    <div
                      className="token-bar-fill"
                      style={{ width: `${((row.tokens || 0) / maxTokens) * 100}%` }}
                    />
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

      {/* Usage by Operation */}
      {byOperation.length > 0 && (
        <div className="token-section">
          <h2><Activity size={20} /> Usage by Operation</h2>
          <div className="token-tier-list">
            {byOperation.map((row) => {
              const pct = totals.total_tokens ? ((row.tokens || 0) / totals.total_tokens * 100) : 0;
              return (
                <div key={row.operation || 'none'} className="token-tier-item">
                  <div className="tier-info">
                    <span className="tier-name">{getOperationLabel(row.operation)}</span>
                    <span className="tier-stats">{row.calls} calls &middot; {formatTokens(row.tokens)} &middot; {formatCost(row.cost_usd)} &middot; <em>{row.models_used}</em></span>
                  </div>
                  <div className="tier-bar-track">
                    <div className="tier-bar-fill operation" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="tier-pct">{pct.toFixed(1)}%</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};

// =============================================================================
// MAIN LOGS PAGE COMPONENT
// =============================================================================
const LogsPage = () => {
  // State Management
  const [activeTab, setActiveTab] = useState('overview');
  const [timePeriod, setTimePeriod] = useState('24h');
  const [systemHealth, setSystemHealth] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [stats, setStats] = useState(null);
  const [activities, setActivities] = useState([]);
  const [agentMetrics, setAgentMetrics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedActivity, setExpandedActivity] = useState(null);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [showHealthBanner, setShowHealthBanner] = useState(true);
  const [tokenData, setTokenData] = useState(null);
  const [tokenLoading, setTokenLoading] = useState(false);
  
  // Auto-refresh interval
  const refreshIntervalRef = useRef(null);

  // =============================================================================
  // DATA FETCHING FUNCTIONS (Using Admin Endpoints)
  // =============================================================================
  
  const fetchSystemHealth = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/system/health`);
      if (response.ok) {
        const data = await response.json();
        setSystemHealth(data);
      }
    } catch (err) {
      console.error('Error fetching system health:', err);
    }
  }, []);

  const fetchAlerts = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/alerts?limit=10`);
      if (response.ok) {
        const data = await response.json();
        setAlerts(data.alerts || []);
      }
    } catch (err) {
      console.error('Error fetching alerts:', err);
    }
  }, []);

  const fetchAdminStats = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/stats?period=${timePeriod}`);
      if (response.ok) {
        const data = await response.json();
        setStats(data);
      }
    } catch (err) {
      console.error('Error fetching admin stats:', err);
    }
  }, [timePeriod]);

  const fetchActivities = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/admin/activity?limit=50`);
      if (response.ok) {
        const data = await response.json();
        setActivities(data.activities || []);
      }
    } catch (err) {
      console.error('Error fetching activities:', err);
      setActivities([]);
    }
  }, []);

  const fetchAgentMetrics = useCallback(async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/agents/metrics`);
      if (response.ok) {
        const data = await response.json();
        setAgentMetrics(data.agents || []);
      }
    } catch (err) {
      console.error('Error fetching agent metrics:', err);
      setAgentMetrics([]);
    }
  }, []);

  const fetchTokenStats = useCallback(async () => {
    setTokenLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/logs/stats?period=${timePeriod}`);
      if (response.ok) {
        const data = await response.json();
        setTokenData(data);
      }
    } catch (err) {
      console.error('Error fetching token stats:', err);
    } finally {
      setTokenLoading(false);
    }
  }, [timePeriod]);

  // =============================================================================
  // REFRESH ALL DATA
  // =============================================================================
  
  const refreshAllData = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await Promise.all([
        fetchSystemHealth(),
        fetchAlerts(),
        fetchAdminStats(),
        fetchActivities(),
        fetchAgentMetrics(),
        fetchTokenStats()
      ]);
      setError(null);
    } catch (err) {
      console.error('Error refreshing data:', err);
      setError('Failed to refresh data. Please try again.');
    } finally {
      setIsRefreshing(false);
      setLoading(false);
    }
  }, [fetchSystemHealth, fetchAlerts, fetchAdminStats, fetchActivities, fetchAgentMetrics, fetchTokenStats]);

  // =============================================================================
  // EFFECTS
  // =============================================================================
  
  useEffect(() => {
    refreshAllData();
    
    // Set up auto-refresh every 30 seconds
    refreshIntervalRef.current = setInterval(refreshAllData, 30000);
    
    return () => {
      if (refreshIntervalRef.current) {
        clearInterval(refreshIntervalRef.current);
      }
    };
  }, [refreshAllData]);

  // Refresh when time period changes
  useEffect(() => {
    fetchAdminStats();
    fetchTokenStats();
  }, [timePeriod, fetchAdminStats, fetchTokenStats]);

  // =============================================================================
  // COMPUTED VALUES
  // =============================================================================
  
  const totalTasks = stats?.total_requests || 0;
  const successRate = stats?.success_rate || 0;
  const avgResponseTime = stats?.avg_response_time || 0;
  const activeServices = agentMetrics.filter(a => a.status === 'operational').length;
  const totalServices = agentMetrics.length || 5;

  // =============================================================================
  // RENDER
  // =============================================================================
  
  if (loading) {
    return (
      <div className="logs-page">
        <div className="loading-container">
          <RefreshCw className="loading-spinner" size={32} />
          <p>Loading monitoring dashboard...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="logs-page">
      {/* System Health Banner */}
      {showHealthBanner && systemHealth && (
        <SystemHealthBanner 
          health={systemHealth} 
          onDismiss={() => setShowHealthBanner(false)}
        />
      )}

      {/* Page Header */}
      <div className="logs-header">
        <div className="header-content">
          <h1>
            <Shield size={28} />
            System Monitoring
          </h1>
          <p className="header-subtitle">
            Real-time overview of your AI assistant services
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

      {/* Alert Banner */}
      {alerts.length > 0 && <AlertBanner alerts={alerts} />}

      {/* Error Message */}
      {error && (
        <div className="error-banner">
          <AlertCircle size={20} />
          <span>{error}</span>
          <button onClick={() => setError(null)}>
            <X size={16} />
          </button>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="tabs-container">
        <div className="tabs">
          <button 
            className={`tab ${activeTab === 'overview' ? 'active' : ''}`}
            onClick={() => setActiveTab('overview')}
          >
            <BarChart3 size={18} />
            Overview
          </button>
          <button 
            className={`tab ${activeTab === 'services' ? 'active' : ''}`}
            onClick={() => setActiveTab('services')}
          >
            <Server size={18} />
            Services
          </button>
          <button 
            className={`tab ${activeTab === 'activity' ? 'active' : ''}`}
            onClick={() => setActiveTab('activity')}
          >
            <Activity size={18} />
            Activity Log
          </button>
          <button 
            className={`tab ${activeTab === 'tokens' ? 'active' : ''}`}
            onClick={() => setActiveTab('tokens')}
          >
            <DollarSign size={18} />
            Token Usage
          </button>
        </div>
      </div>

      {/* Tab Content */}
      <div className="tab-content">
        {/* Overview Tab */}
        {activeTab === 'overview' && (
          <div className="overview-tab">
            {/* Stats Cards */}
            <div className="stats-grid">
              <StatsCard
                icon={Activity}
                title="Total Tasks"
                value={totalTasks.toLocaleString()}
                subtitle={`In the last ${timePeriod}`}
                trend={stats?.trend_total}
                trendDirection={stats?.trend_total_direction || 'up'}
              />
              <StatsCard
                icon={CheckCircle}
                title="Success Rate"
                value={`${successRate.toFixed(1)}%`}
                subtitle="Tasks completed successfully"
                trend={stats?.trend_success}
                trendDirection={successRate >= 90 ? 'up' : 'down'}
              />
              <StatsCard
                icon={Zap}
                title="Avg Response Time"
                value={`${(avgResponseTime / 1000).toFixed(2)}s`}
                subtitle="Average task completion"
                trend={stats?.trend_speed}
                trendDirection="up"
              />
              <StatsCard
                icon={Server}
                title="Active Services"
                value={`${activeServices}/${totalServices}`}
                subtitle="Services operational"
                trendDirection={activeServices === totalServices ? 'up' : 'down'}
              />
            </div>

            {/* Quick Service Overview */}
            <div className="quick-overview">
              <h2>Service Status</h2>
              <div className="service-status-grid">
                {agentMetrics.length > 0 ? (
                  agentMetrics.map((agent, idx) => (
                    <AgentPerformanceCard key={idx} agent={agent} />
                  ))
                ) : (
                  <div className="no-data">
                    <Server size={48} />
                    <p>No service data available</p>
                    <span>Services will appear here once they start processing tasks</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Services Tab */}
        {activeTab === 'services' && (
          <div className="services-tab">
            <div className="services-header">
              <h2>Service Performance</h2>
              <p>Detailed metrics for each AI assistant service</p>
            </div>
            <div className="agents-grid">
              {agentMetrics.length > 0 ? (
                agentMetrics.map((agent, idx) => (
                  <AgentPerformanceCard key={idx} agent={agent} />
                ))
              ) : (
                <div className="no-data">
                  <Server size={48} />
                  <p>No service metrics available</p>
                  <span>Metrics will appear here once services start processing tasks</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Activity Log Tab */}
        {activeTab === 'activity' && (
          <div className="activity-tab">
            <div className="activity-header">
              <h2>Recent Activity</h2>
              <p>Privacy-protected activity log showing service operations</p>
            </div>
            <div className="activity-list">
              {activities.length > 0 ? (
                activities.map((activity, idx) => (
                  <ActivityEntry
                    key={idx}
                    activity={activity}
                    expanded={expandedActivity === idx}
                    onToggle={() => setExpandedActivity(expandedActivity === idx ? null : idx)}
                  />
                ))
              ) : (
                <div className="no-data">
                  <Activity size={48} />
                  <p>No recent activity</p>
                  <span>Activity will appear here as services process tasks</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Token Usage Tab */}
        {activeTab === 'tokens' && (
          <TokenUsageTab tokenData={tokenData} loading={tokenLoading} />
        )}
      </div>
    </div>
  );
};

export default LogsPage;
