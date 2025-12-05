import React, { useState, useEffect, useCallback } from 'react';
import {
  Activity, Clock, CheckCircle, XCircle, AlertTriangle, RefreshCw,
  TrendingUp, Server, Database, FileText, MessageSquare, DollarSign,
  PieChart, AlertCircle, Cpu, Zap, Upload, Search,
  ChevronDown, ChevronUp, Filter, Calendar
} from 'lucide-react';
import '../css/KBAnalyticsPage.css';

// API Base URL for Knowledge Base server
const KB_API_URL = 'http://localhost:8009';

// =============================================================================
// STAT CARD COMPONENT
// =============================================================================
const StatCard = ({ icon: Icon, label, value, subValue, trend, color = 'blue' }) => (
  <div className={`kb-stat-card kb-stat-${color}`}>
    <div className="kb-stat-icon">
      <Icon size={24} />
    </div>
    <div className="kb-stat-content">
      <div className="kb-stat-value">{value}</div>
      <div className="kb-stat-label">{label}</div>
      {subValue && <div className="kb-stat-sub">{subValue}</div>}
      {trend !== undefined && (
        <div className={`kb-stat-trend ${trend >= 0 ? 'positive' : 'negative'}`}>
          <TrendingUp size={14} />
          <span>{trend >= 0 ? '+' : ''}{trend}%</span>
        </div>
      )}
    </div>
  </div>
);

// =============================================================================
// HEALTH STATUS COMPONENT
// =============================================================================
const HealthStatus = ({ health }) => {
  if (!health) return null;

  const getStatusClass = (status) => {
    if (!status) return 'status-error';
    const statusLower = String(status).toLowerCase();
    // Check for positive status indicators
    if (statusLower === 'healthy' || 
        statusLower === 'connected' || 
        statusLower.includes('operational') ||
        status === true) {
      return 'status-healthy';
    }
    // Check for warning status indicators
    if (statusLower === 'degraded' || 
        statusLower === 'warning' || 
        statusLower.includes('minor')) {
      return 'status-warning';
    }
    return 'status-error';
  };

  const getStatusIcon = (status) => {
    if (!status) return <XCircle size={16} />;
    const statusLower = String(status).toLowerCase();
    if (statusLower === 'healthy' || 
        statusLower === 'connected' || 
        statusLower.includes('operational') ||
        status === true) {
      return <CheckCircle size={16} />;
    }
    if (statusLower === 'degraded' || 
        statusLower === 'warning' || 
        statusLower.includes('minor')) {
      return <AlertTriangle size={16} />;
    }
    return <XCircle size={16} />;
  };

  return (
    <div className="kb-health-panel">
      <h3><Server size={18} /> System Health</h3>
      <div className="kb-health-grid">
        <div className={`kb-health-item ${getStatusClass(health.status)}`}>
          {getStatusIcon(health.status)}
          <span>API Status</span>
          <strong>{health.status || 'Unknown'}</strong>
        </div>
        <div className={`kb-health-item ${getStatusClass(health.services?.database?.status)}`}>
          {getStatusIcon(health.services?.database?.status)}
          <span>SQLite</span>
          <strong>{health.services?.database?.status === 'connected' ? 'Connected' : 'Disconnected'}</strong>
        </div>
        <div className={`kb-health-item ${getStatusClass(health.services?.weaviate?.status)}`}>
          {getStatusIcon(health.services?.weaviate?.status)}
          <span>Weaviate</span>
          <strong>
            {health.services?.weaviate?.status === 'connected' 
              ? `Connected (${health.services?.weaviate?.chunks_stored || 0} chunks)` 
              : 'Disconnected'}
          </strong>
        </div>
      </div>
      {health.recent_errors > 0 && (
        <div className="kb-health-errors">
          <AlertCircle size={14} />
          <span>{health.recent_errors} recent errors</span>
        </div>
      )}
    </div>
  );
};

// =============================================================================
// DOCUMENT STATS COMPONENT
// =============================================================================
const DocumentStats = ({ stats }) => {
  if (!stats) return null;

  // Calculate success/failed from success_rate if not provided
  const successRate = stats.success_rate || 100;
  const totalDocs = stats.documents_processed || 0;
  
  // Processing time
  const avgProcessingTime = stats.avg_processing_time_ms 
    ? (stats.avg_processing_time_ms / 1000).toFixed(2) 
    : null;

  return (
    <div className="kb-section-panel">
      <h3><FileText size={18} /> Document Processing <span className="kb-period-badge">{stats.period || '24h'}</span></h3>
      <div className="kb-stats-grid">
        <div className="kb-mini-stat">
          <Upload size={20} />
          <div>
            <strong>{stats.documents_processed || 0}</strong>
            <span>Documents Processed</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <Database size={20} />
          <div>
            <strong>{stats.total_chunks || 0}</strong>
            <span>Total Chunks</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <Zap size={20} />
          <div>
            <strong>{stats.total_tokens?.toLocaleString() || 0}</strong>
            <span>Tokens Used</span>
          </div>
        </div>
        <div className="kb-mini-stat success">
          <CheckCircle size={20} />
          <div>
            <strong>{successRate.toFixed(1)}%</strong>
            <span>Success Rate</span>
          </div>
        </div>
      </div>
      
      {/* Processing Time Section */}
      {totalDocs > 0 && (
        <div className="kb-processing-time">
          <Clock size={14} />
          <span>
            Avg Processing Time: {avgProcessingTime ? `${avgProcessingTime}s` : 'Not tracked yet'}
          </span>
          {avgProcessingTime && parseFloat(avgProcessingTime) > 30 && (
            <span className="kb-time-warning">
              <AlertTriangle size={12} /> Slow
            </span>
          )}
        </div>
      )}
      
      {stats.by_stage && Object.keys(stats.by_stage).length > 0 && (
        <div className="kb-stage-breakdown">
          <h4>Processing Stages</h4>
          <div className="kb-stage-list">
            {Object.entries(stats.by_stage).map(([stage, data]) => (
              <div key={stage} className="kb-stage-item">
                <span className="kb-stage-name">{stage.replace(/_/g, ' ')}</span>
                <span className="kb-stage-count">
                  {typeof data === 'object' ? `${data.calls || 0} calls` : data}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {stats.recent_uploads && stats.recent_uploads.length > 0 && (
        <div className="kb-recent-docs">
          <h4>Recent Uploads</h4>
          <div className="kb-docs-list">
            {stats.recent_uploads.slice(0, 5).map((doc, idx) => (
              <div key={idx} className="kb-doc-item">
                <FileText size={14} />
                <span className="kb-doc-name">{doc.filename || doc.pipeline_id || 'Unknown'}</span>
                <div className="kb-doc-info">
                  <span className="kb-doc-chunks">{doc.chunks || 0} chunks</span>
                  <span className={`kb-doc-status ${doc.status === 'success' ? 'success' : 'failed'}`}>
                    {doc.status === 'success' ? 'Success' : 'Failed'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      
      {(!stats.recent_uploads || stats.recent_uploads.length === 0) && stats.documents_processed === 0 && (
        <div className="kb-no-data">
          <FileText size={24} />
          <span>No documents processed yet</span>
        </div>
      )}
    </div>
  );
};

// =============================================================================
// WEAVIATE DOCUMENTS COMPONENT (Vector Database History)
// =============================================================================
const WeaviateDocuments = ({ data }) => {
  const [expanded, setExpanded] = useState(false);
  
  if (!data) return null;

  const documents = data.documents || [];
  const displayDocs = expanded ? documents : documents.slice(0, 10);

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Unknown';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return dateStr;
    }
  };

  // Format file size
  const formatFileSize = (bytes) => {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
  };

  return (
    <div className="kb-section-panel kb-weaviate-panel">
      <h3><Database size={18} /> Document Upload History</h3>
      <div className="kb-weaviate-summary">
        <div className="kb-weaviate-stat">
          <strong>{data.total_documents || 0}</strong>
          <span>Documents</span>
        </div>
        <div className="kb-weaviate-stat">
          <strong>{data.total_chunks || 0}</strong>
          <span>Total Chunks</span>
        </div>
      </div>
      
      {documents.length > 0 ? (
        <>
          {/* Table Header */}
          <div className="kb-weaviate-header">
            <span>Filename</span>
            <span>Chunks</span>
            <span>Uploaded By</span>
            <span>Ver.</span>
            <span>Upload Date</span>
          </div>
          
          <div className="kb-weaviate-list">
            {displayDocs.map((doc, idx) => (
              <div key={doc.doc_id || idx} className="kb-weaviate-item">
                <div className="kb-weaviate-col-filename">
                  <FileText size={14} />
                  <span className="kb-weaviate-filename-text" title={doc.filename}>
                    {doc.filename || 'Unknown'}
                  </span>
                  {doc.file_size_bytes > 0 && (
                    <span className="kb-weaviate-filesize">({formatFileSize(doc.file_size_bytes)})</span>
                  )}
                </div>
                <div className="kb-weaviate-col-chunks">
                  <span className="kb-weaviate-total-chunks">{doc.total_chunks || 0}</span>
                </div>
                <div className="kb-weaviate-col-uploader">
                  <span>{doc.uploaded_by || 'anonymous'}</span>
                </div>
                <div className="kb-weaviate-col-version">
                  <span className="kb-weaviate-version">v{doc.version || 1}</span>
                </div>
                <div className="kb-weaviate-col-date">
                  <span>{formatDate(doc.upload_date)}</span>
                </div>
              </div>
            ))}
          </div>
          {documents.length > 10 && (
            <button className="kb-show-more" onClick={() => setExpanded(!expanded)}>
              {expanded ? (
                <>Show Less <ChevronUp size={16} /></>
              ) : (
                <>Show All ({documents.length}) <ChevronDown size={16} /></>
              )}
            </button>
          )}
        </>
      ) : (
        <div className="kb-no-data">
          <Database size={24} />
          <span>No documents uploaded yet</span>
        </div>
      )}
    </div>
  );
};

// =============================================================================
// CHAT STATS COMPONENT
// =============================================================================
const ChatStats = ({ stats }) => {
  if (!stats) return null;

  // API returns total_messages instead of total_queries
  const totalMessages = stats.total_messages || 0;
  const totalSessions = stats.total_sessions || 0;
  const avgPerSession = totalSessions > 0 ? (totalMessages / totalSessions).toFixed(1) : '0';
  
  // Response time formatting
  const avgResponseTime = stats.avg_response_time_ms ? (stats.avg_response_time_ms / 1000).toFixed(2) : null;
  const p95ResponseTime = stats.p95_response_time_ms ? (stats.p95_response_time_ms / 1000).toFixed(2) : null;
  
  // Chunk stats from search_stats
  const avgChunksRetrieved = stats.search_stats?.avg_chunks_retrieved || 0;
  const avgChunksUsed = stats.search_stats?.avg_chunks_used || 0;

  return (
    <div className="kb-section-panel">
      <h3><MessageSquare size={18} /> Chat Analytics <span className="kb-period-badge">{stats.period || '24h'}</span></h3>
      <div className="kb-stats-grid">
        <div className="kb-mini-stat">
          <MessageSquare size={20} />
          <div>
            <strong>{totalSessions}</strong>
            <span>Total Sessions</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <Search size={20} />
          <div>
            <strong>{totalMessages}</strong>
            <span>Total Messages</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <Zap size={20} />
          <div>
            <strong>{stats.total_tokens?.toLocaleString() || 0}</strong>
            <span>Tokens Used</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <Activity size={20} />
          <div>
            <strong>{avgPerSession}</strong>
            <span>Msgs/Session</span>
          </div>
        </div>
      </div>

      {/* Response Time Metrics */}
      <div className="kb-response-times">
        <h4><Clock size={16} /> Response Times</h4>
        <div className="kb-response-grid">
          <div className="kb-response-item">
            <span>Average</span>
            <strong className={avgResponseTime && parseFloat(avgResponseTime) > 5 ? 'warning' : ''}>
              {avgResponseTime ? `${avgResponseTime}s` : 'N/A'}
            </strong>
          </div>
          <div className="kb-response-item">
            <span>P95</span>
            <strong className={p95ResponseTime && parseFloat(p95ResponseTime) > 10 ? 'warning' : ''}>
              {p95ResponseTime ? `${p95ResponseTime}s` : 'N/A'}
            </strong>
          </div>
        </div>
      </div>

      {/* Search Performance - show even if values are 0 after some messages */}
      {totalMessages > 0 && (
        <div className="kb-search-stats">
          <h4><Database size={16} /> RAG Performance</h4>
          <div className="kb-search-grid">
            <div className="kb-search-item">
              <span>Avg Chunks Retrieved</span>
              <strong>{avgChunksRetrieved.toFixed(1)}</strong>
            </div>
            <div className="kb-search-item">
              <span>Avg Chunks Used</span>
              <strong>{avgChunksUsed.toFixed(1)}</strong>
            </div>
          </div>
        </div>
      )}

      {stats.by_stage && Object.keys(stats.by_stage).length > 0 && (
        <div className="kb-stage-breakdown">
          <h4>Chat Stages</h4>
          <div className="kb-stage-list">
            {Object.entries(stats.by_stage).map(([stage, data]) => (
              <div key={stage} className="kb-stage-item">
                <span className="kb-stage-name">{stage.replace(/_/g, ' ')}</span>
                <span className="kb-stage-count">
                  {typeof data === 'object' ? `${data.calls || 0} calls` : data}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
      
      {totalSessions === 0 && (
        <div className="kb-no-data">
          <MessageSquare size={24} />
          <span>No chat sessions yet</span>
        </div>
      )}
    </div>
  );
};

// =============================================================================
// COST TRACKING COMPONENT
// =============================================================================
const CostTracking = ({ costs }) => {
  if (!costs) return null;

  const formatCost = (cost) => {
    if (cost === undefined || cost === null) return '$0.00';
    return `$${parseFloat(cost).toFixed(4)}`;
  };

  const formatTokens = (tokens) => {
    if (!tokens) return '0';
    if (tokens >= 1000000) return `${(tokens / 1000000).toFixed(2)}M`;
    if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
    return tokens.toString();
  };

  // API returns total_cost_usd and by_operation
  const totalCost = costs.total_cost_usd || costs.total_cost || 0;
  const hasData = totalCost > 0 || (costs.by_model && Object.keys(costs.by_model).length > 0);

  return (
    <div className="kb-section-panel kb-cost-panel">
      <h3><DollarSign size={18} /> Cost & Token Usage <span className="kb-period-badge">{costs.period || '30d'}</span></h3>
      
      <div className="kb-cost-summary">
        <div className="kb-cost-total">
          <span>Total Estimated Cost</span>
          <strong>{formatCost(totalCost)}</strong>
        </div>
        {costs.by_operation && (
          <>
            <div className="kb-cost-breakdown">
              <span>Document Processing</span>
              <strong>{formatCost(costs.by_operation.document_processing)}</strong>
            </div>
            <div className="kb-cost-breakdown">
              <span>Chat Usage</span>
              <strong>{formatCost(costs.by_operation.chat)}</strong>
            </div>
          </>
        )}
      </div>

      {costs.by_model && Object.keys(costs.by_model).length > 0 && (
        <div className="kb-model-breakdown">
          <h4>Usage by Model</h4>
          <div className="kb-model-table">
            <div className="kb-model-header">
              <span>Model</span>
              <span>Tokens</span>
              <span>Cost</span>
            </div>
            {Object.entries(costs.by_model).map(([model, data]) => (
              <div key={model} className="kb-model-row">
                <span className="kb-model-name">
                  <Cpu size={14} />
                  {model}
                </span>
                <span className="kb-model-tokens">
                  {typeof data === 'object' ? formatTokens(data.tokens) : '-'}
                </span>
                <span className="kb-model-cost">
                  {typeof data === 'object' ? formatCost(data.cost) : formatCost(data)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {costs.daily_trend && costs.daily_trend.length > 0 && (
        <div className="kb-daily-trend">
          <h4>Daily Trend</h4>
          <div className="kb-trend-list">
            {costs.daily_trend.slice(-7).map((day, idx) => (
              <div key={idx} className="kb-trend-item">
                <span className="kb-trend-date">{day.date}</span>
                <span className="kb-trend-cost">{formatCost(day.cost)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      
      {!hasData && (
        <div className="kb-no-data">
          <DollarSign size={24} />
          <span>No cost data recorded yet</span>
        </div>
      )}
    </div>
  );
};

// =============================================================================
// ERROR LOG COMPONENT
// =============================================================================
const ErrorLog = ({ errors }) => {
  const [expanded, setExpanded] = useState(false);

  if (!errors || errors.length === 0) {
    return (
      <div className="kb-section-panel kb-error-panel">
        <h3><AlertCircle size={18} /> Recent Errors</h3>
        <div className="kb-no-errors">
          <CheckCircle size={32} />
          <span>No recent errors</span>
        </div>
      </div>
    );
  }

  const displayErrors = expanded ? errors : errors.slice(0, 5);

  return (
    <div className="kb-section-panel kb-error-panel">
      <h3>
        <AlertCircle size={18} /> 
        Recent Errors
        <span className="kb-error-count">{errors.length}</span>
      </h3>
      <div className="kb-error-list">
        {displayErrors.map((error, idx) => (
          <div key={idx} className="kb-error-item">
            <div className="kb-error-header">
              <span className={`kb-error-type ${error.pipeline_type || 'unknown'}`}>
                {error.pipeline_type || 'System'}
              </span>
              <span className="kb-error-stage">{error.stage || 'Unknown'}</span>
              <span className="kb-error-time">
                {error.timestamp ? new Date(error.timestamp).toLocaleString() : 'N/A'}
              </span>
            </div>
            <div className="kb-error-message">{error.error_message || error.error || 'Unknown error'}</div>
          </div>
        ))}
      </div>
      {errors.length > 5 && (
        <button className="kb-show-more" onClick={() => setExpanded(!expanded)}>
          {expanded ? (
            <>Show Less <ChevronUp size={16} /></>
          ) : (
            <>Show All ({errors.length}) <ChevronDown size={16} /></>
          )}
        </button>
      )}
    </div>
  );
};

// =============================================================================
// ACTIVITY LOGS COMPONENT
// =============================================================================
const ActivityLogs = ({ logs, loading, onFilterChange, onRefresh }) => {
  const [expanded, setExpanded] = useState(false);
  const [filter, setFilter] = useState('all');

  const handleFilterChange = (newFilter) => {
    setFilter(newFilter);
    if (onFilterChange) onFilterChange(newFilter);
  };

  const formatTimestamp = (ts) => {
    if (!ts) return 'Unknown';
    try {
      const date = new Date(ts);
      const now = new Date();
      const diffMs = now - date;
      const diffMins = Math.floor(diffMs / 60000);
      const diffHours = Math.floor(diffMs / 3600000);
      
      if (diffMins < 1) return 'Just now';
      if (diffMins < 60) return `${diffMins}m ago`;
      if (diffHours < 24) return `${diffHours}h ago`;
      return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return ts;
    }
  };

  const getLogIcon = (type, success) => {
    if (type === 'document') {
      return success ? <FileText size={16} className="log-icon success" /> : <FileText size={16} className="log-icon error" />;
    }
    if (type === 'chat') {
      return success ? <MessageSquare size={16} className="log-icon success" /> : <MessageSquare size={16} className="log-icon error" />;
    }
    if (type === 'error') {
      return <AlertCircle size={16} className="log-icon error" />;
    }
    return <Activity size={16} className="log-icon" />;
  };

  const getLogTypeClass = (type) => {
    if (type === 'document') return 'log-type-document';
    if (type === 'chat') return 'log-type-chat';
    if (type === 'error') return 'log-type-error';
    return 'log-type-system';
  };

  const displayLogs = expanded ? (logs || []) : (logs || []).slice(0, 10);

  return (
    <div className="kb-section-panel kb-activity-panel">
      <div className="kb-activity-header">
        <h3><Activity size={18} /> Activity Logs</h3>
        <div className="kb-activity-controls">
          <div className="kb-filter-buttons">
            <button 
              className={`kb-filter-btn ${filter === 'all' ? 'active' : ''}`}
              onClick={() => handleFilterChange('all')}
            >
              All
            </button>
            <button 
              className={`kb-filter-btn ${filter === 'documents' ? 'active' : ''}`}
              onClick={() => handleFilterChange('documents')}
            >
              <FileText size={14} /> Docs
            </button>
            <button 
              className={`kb-filter-btn ${filter === 'chat' ? 'active' : ''}`}
              onClick={() => handleFilterChange('chat')}
            >
              <MessageSquare size={14} /> Chat
            </button>
            <button 
              className={`kb-filter-btn ${filter === 'errors' ? 'active' : ''}`}
              onClick={() => handleFilterChange('errors')}
            >
              <AlertCircle size={14} /> Errors
            </button>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="kb-activity-loading">
          <RefreshCw size={20} className="spinning" />
          <span>Loading logs...</span>
        </div>
      ) : (!logs || logs.length === 0) ? (
        <div className="kb-no-data">
          <Activity size={24} />
          <span>No activity logs found</span>
        </div>
      ) : (
        <>
          <div className="kb-activity-list">
            {displayLogs.map((log, idx) => (
              <div key={idx} className={`kb-activity-item ${log.success === false ? 'failed' : ''}`}>
                <div className="kb-activity-icon">
                  {getLogIcon(log.type, log.success)}
                </div>
                <div className="kb-activity-content">
                  <div className="kb-activity-main">
                    <span className={`kb-activity-type ${getLogTypeClass(log.type)}`}>
                      {log.type?.toUpperCase()}
                    </span>
                    <span className="kb-activity-action">{log.action}</span>
                    {log.target && (
                      <span className="kb-activity-target">{log.target}</span>
                    )}
                  </div>
                  <div className="kb-activity-meta">
                    {log.details?.tokens > 0 && (
                      <span className="kb-activity-detail">
                        <Zap size={12} /> {log.details.tokens.toLocaleString()} tokens
                      </span>
                    )}
                    {log.details?.chunks_created > 0 && (
                      <span className="kb-activity-detail">
                        <Database size={12} /> {log.details.chunks_created} chunks
                      </span>
                    )}
                    {log.details?.duration_ms > 0 && (
                      <span className="kb-activity-detail">
                        <Clock size={12} /> {(log.details.duration_ms / 1000).toFixed(1)}s
                      </span>
                    )}
                    {log.details?.uploaded_by && log.details.uploaded_by !== 'System' && (
                      <span className="kb-activity-detail">
                        by {log.details.uploaded_by}
                      </span>
                    )}
                  </div>
                  {log.error && (
                    <div className="kb-activity-error">
                      <AlertTriangle size={12} />
                      <span>{log.error}</span>
                    </div>
                  )}
                </div>
                <div className="kb-activity-time">
                  {formatTimestamp(log.timestamp)}
                </div>
              </div>
            ))}
          </div>
          
          {logs.length > 10 && (
            <button className="kb-show-more" onClick={() => setExpanded(!expanded)}>
              {expanded ? (
                <>Show Less <ChevronUp size={16} /></>
              ) : (
                <>Show All ({logs.length}) <ChevronDown size={16} /></>
              )}
            </button>
          )}
        </>
      )}
    </div>
  );
};

// =============================================================================
// MAIN KB ANALYTICS PAGE COMPONENT
// =============================================================================
const KBAnalyticsPage = () => {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  
  // Section visibility filters
  const [visibleSections, setVisibleSections] = useState({
    documents: true,
    chat: true,
    cost: true,
    activity: true
  });
  
  // Time range filter
  const [timeRange, setTimeRange] = useState('24h');
  

  
  // Data states
  const [health, setHealth] = useState(null);
  const [documentStats, setDocumentStats] = useState(null);
  const [chatStats, setChatStats] = useState(null);
  const [costs, setCosts] = useState(null);
  const [errors, setErrors] = useState([]);
  const [aggregateStats, setAggregateStats] = useState(null);
  const [weaviateDocs, setWeaviateDocs] = useState(null);
  const [activityLogs, setActivityLogs] = useState([]);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityFilter, setActivityFilter] = useState('all');

  // Toggle section visibility
  const toggleSection = (section) => {
    setVisibleSections(prev => ({
      ...prev,
      [section]: !prev[section]
    }));
  };



  // Get hours from time range
  const getHoursFromTimeRange = (range) => {
    switch (range) {
      case '1h': return 1;
      case '6h': return 6;
      case '24h': return 24;
      case '7d': return 168;
      case '30d': return 720;
      case 'all': return 99999; // Large number for all time
      default: return 24;
    }
  };

  // Get days from time range (for costs endpoint)
  const getDaysFromTimeRange = (range) => {
    switch (range) {
      case '1h': return 1;
      case '6h': return 1;
      case '24h': return 1;
      case '7d': return 7;
      case '30d': return 30;
      case 'all': return 9999; // Large number for all time
      default: return 1;
    }
  };

  // Fetch all data
  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    const hours = getHoursFromTimeRange(timeRange);
    const days = getDaysFromTimeRange(timeRange);

    try {
      // Fetch all endpoints in parallel
      const [healthRes, docsRes, chatRes, costsRes, errorsRes, statsRes, weaviateRes, activityRes] = await Promise.allSettled([
        fetch(`${KB_API_URL}/admin/health`),
        fetch(`${KB_API_URL}/admin/documents?period=${timeRange}`),
        fetch(`${KB_API_URL}/admin/chat-stats?period=${timeRange}`),
        fetch(`${KB_API_URL}/admin/costs?days=${days}`),
        fetch(`${KB_API_URL}/admin/errors?limit=20`),
        fetch(`${KB_API_URL}/admin/stats`),
        fetch(`${KB_API_URL}/admin/weaviate-documents`),
        fetch(`${KB_API_URL}/admin/activity-logs?hours=${hours}&limit=50&log_type=${activityFilter}`)
      ]);

      // Process health
      if (healthRes.status === 'fulfilled' && healthRes.value.ok) {
        const data = await healthRes.value.json();
        setHealth(data);
      }

      // Process document stats
      if (docsRes.status === 'fulfilled' && docsRes.value.ok) {
        const data = await docsRes.value.json();
        setDocumentStats(data);
      }

      // Process chat stats
      if (chatRes.status === 'fulfilled' && chatRes.value.ok) {
        const data = await chatRes.value.json();
        setChatStats(data);
      }

      // Process costs
      if (costsRes.status === 'fulfilled' && costsRes.value.ok) {
        const data = await costsRes.value.json();
        setCosts(data);
      }

      // Process errors
      if (errorsRes.status === 'fulfilled' && errorsRes.value.ok) {
        const data = await errorsRes.value.json();
        setErrors(data.errors || []);
      }

      // Process activity logs
      if (activityRes.status === 'fulfilled' && activityRes.value.ok) {
        const data = await activityRes.value.json();
        setActivityLogs(data.logs || []);
      }

      // Process aggregate stats
      if (statsRes.status === 'fulfilled' && statsRes.value.ok) {
        const data = await statsRes.value.json();
        setAggregateStats(data);
      }

      // Process Weaviate documents
      if (weaviateRes.status === 'fulfilled' && weaviateRes.value.ok) {
        const data = await weaviateRes.value.json();
        setWeaviateDocs(data);
      }

      setLastUpdated(new Date());
    } catch (err) {
      console.error('Error fetching KB analytics:', err);
      setError('Failed to connect to Knowledge Base server. Make sure it is running on port 8009.');
    } finally {
      setLoading(false);
    }
  }, [timeRange, activityFilter]);

  // Fetch activity logs with filter
  const fetchActivityLogs = useCallback(async (filter = 'all') => {
    setActivityLoading(true);
    const hours = getHoursFromTimeRange(timeRange);
    try {
      const res = await fetch(`${KB_API_URL}/admin/activity-logs?hours=${hours}&limit=50&log_type=${filter}`);
      if (res.ok) {
        const data = await res.json();
        setActivityLogs(data.logs || []);
      }
    } catch (err) {
      console.error('Error fetching activity logs:', err);
    } finally {
      setActivityLoading(false);
    }
  }, [timeRange]);

  // Handle activity filter change
  const handleActivityFilterChange = (newFilter) => {
    setActivityFilter(newFilter);
    fetchActivityLogs(newFilter);
  };

  // Initial load
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchData, 30000); // 30 seconds
    return () => clearInterval(interval);
  }, [autoRefresh, fetchData]);

  return (
    <div className="kb-analytics-page">
      {/* Header */}
      <div className="kb-analytics-header">
        <div className="kb-header-left">
          <h1><Database size={28} /> Knowledge Base Analytics</h1>
          <p>Monitor document processing, chat usage, and system health</p>
        </div>
        <div className="kb-header-right">
          <label className="kb-auto-refresh">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
            />
            <span>Auto-refresh</span>
          </label>
          <button className="kb-refresh-btn" onClick={fetchData} disabled={loading}>
            <RefreshCw size={18} className={loading ? 'spinning' : ''} />
            Refresh
          </button>
          {lastUpdated && (
            <span className="kb-last-updated">
              <Clock size={14} />
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
        </div>
      </div>

      {/* Filters Bar */}
      <div className="kb-filters-bar">
        <div className="kb-section-filters">
          <span className="kb-filter-label"><Filter size={16} /> Show:</span>
          <button 
            className={`kb-section-toggle ${visibleSections.documents ? 'active' : ''}`}
            onClick={() => toggleSection('documents')}
          >
            <FileText size={16} />
            Document Processing
          </button>
          <button 
            className={`kb-section-toggle ${visibleSections.chat ? 'active' : ''}`}
            onClick={() => toggleSection('chat')}
          >
            <MessageSquare size={16} />
            Chat Analytics
          </button>
          <button 
            className={`kb-section-toggle ${visibleSections.cost ? 'active' : ''}`}
            onClick={() => toggleSection('cost')}
          >
            <DollarSign size={16} />
            Cost & Token
          </button>
          <button 
            className={`kb-section-toggle ${visibleSections.activity ? 'active' : ''}`}
            onClick={() => toggleSection('activity')}
          >
            <Activity size={16} />
            Activity Logs
          </button>
        </div>
        <div className="kb-time-filter">
          <Calendar size={16} />
          <select 
            value={timeRange} 
            onChange={(e) => setTimeRange(e.target.value)}
            className="kb-time-select"
          >
            <option value="1h">Last 1 Hour</option>
            <option value="6h">Last 6 Hours</option>
            <option value="24h">Last 24 Hours</option>
            <option value="7d">Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
            <option value="all">All Time</option>
          </select>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="kb-error-banner">
          <AlertTriangle size={20} />
          <span>{error}</span>
          <button onClick={() => setError(null)}>×</button>
        </div>
      )}

      {/* Loading State */}
      {loading && !health && (
        <div className="kb-loading">
          <RefreshCw size={32} className="spinning" />
          <span>Loading analytics...</span>
        </div>
      )}

      {/* Main Content */}
      {!loading || health ? (
        <div className="kb-analytics-content">
          {/* Top Stats Cards */}
          <div className="kb-stat-cards">
            <StatCard
              icon={FileText}
              label="Documents Processed"
              value={documentStats?.documents_processed || 0}
              subValue={`${documentStats?.total_chunks || 0} chunks`}
              color="blue"
            />
            <StatCard
              icon={MessageSquare}
              label="Chat Sessions"
              value={chatStats?.total_sessions || 0}
              subValue={`${chatStats?.total_messages || 0} messages`}
              color="green"
            />
            <StatCard
              icon={Zap}
              label="Total Tokens"
              value={(() => {
                const docTokens = documentStats?.total_tokens || 0;
                const chatTokens = chatStats?.total_tokens || 0;
                const total = docTokens + chatTokens;
                if (total >= 1000000) return `${(total / 1000000).toFixed(2)}M`;
                if (total >= 1000) return `${(total / 1000).toFixed(1)}K`;
                return total.toString();
              })()}
              subValue="across all models"
              color="purple"
            />
            <StatCard
              icon={DollarSign}
              label="Estimated Cost"
              value={costs?.total_cost_usd ? `$${parseFloat(costs.total_cost_usd).toFixed(4)}` : '$0.00'}
              subValue={`period: ${costs?.period || '30d'}`}
              color="orange"
            />
          </div>

          {/* Health Status */}
          <HealthStatus health={health} />

          {/* Weaviate Documents (Vector Database) */}
          <WeaviateDocuments data={weaviateDocs} />

          {/* Two Column Layout - Document and Chat Stats */}
          <div className="kb-two-columns">
            {visibleSections.documents && (
              <DocumentStats stats={documentStats} />
            )}
            {visibleSections.chat && (
              <ChatStats stats={chatStats} />
            )}
          </div>

          {/* Cost Tracking */}
          {visibleSections.cost && (
            <CostTracking costs={costs} />
          )}

          {/* Activity Logs */}
          {visibleSections.activity && (
            <ActivityLogs 
              logs={activityLogs} 
              loading={activityLoading}
              onFilterChange={handleActivityFilterChange}
            />
          )}

          {/* Error Log (legacy - keeping for backwards compatibility) */}
          {errors.length > 0 && <ErrorLog errors={errors} />}
        </div>
      ) : null}
    </div>
  );
};

export default KBAnalyticsPage;
