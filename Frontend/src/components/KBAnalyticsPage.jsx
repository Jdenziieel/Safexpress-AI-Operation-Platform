import React, { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Filter } from 'lucide-react';
import '../css/KBAnalyticsPage.css';
import { kbApi } from '../api';

const ActionButton = ({ icon: Icon, children, className = '', ...props }) => (
  <div style={{ position: 'relative', display: 'inline-block' }}>
    <button
      className={`main-card-btn ${className}`}
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '12px', fontSize: '1.15rem', fontWeight: 800 }}
      {...props}
    >
      <Icon size={20} />
    </button>
    <span
      style={{
        position: 'absolute',
        top: '100%',
        left: '50%',
        transform: 'translateX(-50%)',
        marginTop: '8px',
        padding: '6px 12px',
        background: '#26326e',
        color: 'white',
        borderRadius: '6px',
        fontSize: '0.85rem',
        fontWeight: 600,
        whiteSpace: 'nowrap',
        opacity: 0,
        pointerEvents: 'none',
        transition: 'opacity 0.2s',
        zIndex: 1000
      }}
      className="button-tooltip"
    >
      {children}
    </span>
  </div>
);

// =============================================================================
// STAT CARD COMPONENT
// =============================================================================
const StatCard = ({ label, value, subValue, trend, color = 'blue' }) => (
  <div className={`kb-stat-card kb-stat-${color}`}>
    <div className="kb-stat-content">
      <div className="kb-stat-value">{value}</div>
      <div className="kb-stat-label">{label}</div>
      {subValue && <div className="kb-stat-sub">{subValue}</div>}
      {trend !== undefined && (
        <div className={`kb-stat-trend ${trend >= 0 ? 'positive' : 'negative'}`}>
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

  // SQLite tile removed: this stack runs on AWS Lambda + DynamoDB +
  // Weaviate. There is no SQLite anywhere in production — that field
  // was leftover from the local-dev FastAPI version of the backend
  // and the admin-health Lambda never returns `services.database`,
  // so the tile always read "Disconnected" and confused users.
  return (
    <div className="kb-health-panel">
      <h3>System Health</h3>
      <div className="kb-health-grid">
        <div className={`kb-health-item ${getStatusClass(health.status)}`}>
          <span>API Status</span>
          <strong>{health.status || 'Unknown'}</strong>
        </div>
        <div className={`kb-health-item ${getStatusClass(health.services?.openai?.status)}`}>
          <span>OpenAI</span>
          <strong>
            {health.services?.openai?.status === 'configured'
              ? 'Configured'
              : (health.services?.openai?.status || 'Unknown')}
          </strong>
        </div>
        <div className={`kb-health-item ${getStatusClass(health.services?.weaviate?.status)}`}>
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
      <h3>Document Processing <span className="kb-period-badge">{stats.period || '24h'}</span></h3>
      <div className="kb-stats-grid">
        <div className="kb-mini-stat">
          <div>
            <strong>{stats.documents_processed || 0}</strong>
            <span>Documents Processed</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <div>
            <strong>{stats.total_chunks || 0}</strong>
            <span>Total Chunks</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <div>
            <strong>{stats.total_tokens?.toLocaleString() || 0}</strong>
            <span>Tokens Used</span>
          </div>
        </div>
        <div className="kb-mini-stat success">
          <div>
            <strong>{successRate.toFixed(1)}%</strong>
            <span>Success Rate</span>
          </div>
        </div>
      </div>
      
      {/* Processing Time Section */}
      {totalDocs > 0 && (
        <div className="kb-processing-time">
          <span>
            Avg Processing Time: {avgProcessingTime ? `${avgProcessingTime}s` : 'Not tracked yet'}
          </span>
          {avgProcessingTime && parseFloat(avgProcessingTime) > 30 && (
            <span className="kb-time-warning">
              Slow
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
      <h3>Document Upload History</h3>
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
                <>Show Less</>
              ) : (
                <>Show All ({documents.length})</>
              )}
            </button>
          )}
        </>
      ) : (
        <div className="kb-no-data">
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
  
  return (
    <div className="kb-section-panel">
      <h3>Chat Analytics <span className="kb-period-badge">{stats.period || '24h'}</span></h3>
      <div className="kb-stats-grid">
        <div className="kb-mini-stat">
          <div>
            <strong>{totalSessions}</strong>
            <span>Total Sessions</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <div>
            <strong>{totalMessages}</strong>
            <span>Total Messages</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <div>
            <strong>{stats.total_tokens?.toLocaleString() || 0}</strong>
            <span>Tokens Used</span>
          </div>
        </div>
        <div className="kb-mini-stat">
          <div>
            <strong>{avgPerSession}</strong>
            <span>Msgs/Session</span>
          </div>
        </div>
      </div>

      {/* Response Time Metrics */}
      <div className="kb-response-times">
        <h4>Response Times</h4>
        <div className="kb-response-grid">
          <div className="kb-response-item">
            <span>Average</span>
            <strong className={avgResponseTime && parseFloat(avgResponseTime) > 5 ? 'warning' : ''}>
              {avgResponseTime ? `${avgResponseTime}s` : 'N/A'}
            </strong>
          </div>
        </div>
      </div>



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

  // Backend returns: { period_days, document_processing: {total_tokens, total_cost_usd},
  //                    chat: {total_tokens, total_cost_usd}, total: {tokens, cost_usd} }
  const docCost = costs.document_processing?.total_cost_usd || 0;
  const chatCost = costs.chat?.total_cost_usd || 0;
  const totalCost = costs.total?.cost_usd || (docCost + chatCost);
  const docTokens = costs.document_processing?.total_tokens || 0;
  const chatTokens = costs.chat?.total_tokens || 0;
  const totalTokens = costs.total?.tokens || (docTokens + chatTokens);
  const periodLabel = costs.period_days ? `${costs.period_days}d` : (costs.period || '30d');
  const hasData = totalCost > 0 || totalTokens > 0;

  return (
    <div className="kb-section-panel kb-cost-panel">
      <h3>Cost & Token Usage <span className="kb-period-badge">{periodLabel}</span></h3>
      
      <div className="kb-cost-summary">
        <div className="kb-cost-total">
          <span>Total Estimated Cost</span>
          <strong>{formatCost(totalCost)}</strong>
        </div>
        <div className="kb-cost-breakdown">
          <span>Document Processing</span>
          <strong>{formatCost(docCost)}</strong>
        </div>
        <div className="kb-cost-breakdown">
          <span>Chat Usage</span>
          <strong>{formatCost(chatCost)}</strong>
        </div>
      </div>

      {/* Token breakdown by category */}
      {hasData && (
        <div className="kb-model-breakdown">
          <h4>Token Breakdown</h4>
          <div className="kb-model-table">
            <div className="kb-model-header">
              <span>Category</span>
              <span>Tokens</span>
              <span>Cost</span>
            </div>
            <div className="kb-model-row">
              <span className="kb-model-name">
                Document Parsing
              </span>
              <span className="kb-model-tokens">{formatTokens(docTokens)}</span>
              <span className="kb-model-cost">{formatCost(docCost)}</span>
            </div>
            <div className="kb-model-row">
              <span className="kb-model-name">
                Chat Queries
              </span>
              <span className="kb-model-tokens">{formatTokens(chatTokens)}</span>
              <span className="kb-model-cost">{formatCost(chatCost)}</span>
            </div>
            <div className="kb-model-row" style={{fontWeight: 600, borderTop: '1px solid var(--border-color, #e2e8f0)'}}>
              <span className="kb-model-name">Total</span>
              <span className="kb-model-tokens">{formatTokens(totalTokens)}</span>
              <span className="kb-model-cost">{formatCost(totalCost)}</span>
            </div>
          </div>
        </div>
      )}
      
      {!hasData && (
        <div className="kb-no-data">
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
        <h3>Recent Errors</h3>
        <div className="kb-no-errors">
          <span>No recent errors</span>
        </div>
      </div>
    );
  }

  const displayErrors = expanded ? errors : errors.slice(0, 5);

  return (
    <div className="kb-section-panel kb-error-panel">
      <h3>
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
            <>Show Less</>
          ) : (
            <>Show All ({errors.length})</>
          )}
        </button>
      )}
    </div>
  );
};

// =============================================================================
// ACTIVITY LOGS COMPONENT
// =============================================================================
const ActivityLogs = ({ logs, loading, onFilterChange }) => {
  const [expanded, setExpanded] = useState(false);
  const [filter, setFilter] = useState('all');
  const [searchTerm, setSearchTerm] = useState('');

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

  const getLogTypeClass = (type) => {
    if (type === 'document') return 'log-type-document';
    if (type === 'chat') return 'log-type-chat';
    if (type === 'error') return 'log-type-error';
    return 'log-type-system';
  };

  const filteredLogs = (logs || []).filter(log => {
    if (!searchTerm) return true;
    const search = searchTerm.toLowerCase();
    return (
      (log.action && log.action.toLowerCase().includes(search)) ||
      (log.target && log.target.toLowerCase().includes(search)) ||
      (log.type && log.type.toLowerCase().includes(search)) ||
      (log.error && log.error.toLowerCase().includes(search)) ||
      (log.details?.uploaded_by && log.details.uploaded_by.toLowerCase().includes(search))
    );
  });
  const displayLogs = expanded ? filteredLogs : filteredLogs.slice(0, 10);

  return (
    <div className="kb-section-panel kb-activity-panel">
      <div className="kb-activity-header">
        <h3>Activity Logs</h3>
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
              Docs
            </button>
            <button 
              className={`kb-filter-btn ${filter === 'chat' ? 'active' : ''}`}
              onClick={() => handleFilterChange('chat')}
            >
              Chat
            </button>
            <button 
              className={`kb-filter-btn ${filter === 'errors' ? 'active' : ''}`}
              onClick={() => handleFilterChange('errors')}
            >
              Errors
            </button>
          </div>
          <div className="kb-activity-search">
            <input
              type="text"
              placeholder="Search logs..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="kb-activity-search-input"
            />
          </div>
        </div>
      </div>

      {loading ? (
        <div className="kb-activity-loading">
          <span>Loading logs...</span>
        </div>
      ) : (!logs || logs.length === 0) ? (
        <div className="kb-no-data">
          <span>No activity logs found</span>
        </div>
      ) : (
        <>
          <div className="kb-activity-list">
            {displayLogs.map((log, idx) => (
              <div key={idx} className={`kb-activity-item ${log.success === false ? 'failed' : ''}`}>
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
                        {log.details.tokens.toLocaleString()} tokens
                      </span>
                    )}
                    {log.details?.chunks_created > 0 && (
                      <span className="kb-activity-detail">
                        {log.details.chunks_created} chunks
                      </span>
                    )}
                    {log.details?.duration_ms > 0 && (
                      <span className="kb-activity-detail">
                        {(log.details.duration_ms / 1000).toFixed(1)}s
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
          
          {filteredLogs.length > 10 && (
            <button className="kb-show-more" onClick={() => setExpanded(!expanded)}>
              {expanded ? (
                <>Show Less</>
              ) : (
                <>Show All ({filteredLogs.length})</>
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
  const [showFilters, setShowFilters] = useState(true);
  
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
      // Fetch all endpoints in parallel using kbApi
      // Routes are /api/kb-admin/* as deployed in API Gateway
      const [healthRes, statsRes, chatRes, costsRes, errorsRes, weaviateRes, activityRes] = await Promise.allSettled([
        kbApi.get('/api/kb-admin/health'),
        kbApi.get(`/api/kb-admin/stats?period=${timeRange}`),
        kbApi.get(`/api/kb-admin/chat-stats?period=${timeRange}`),
        kbApi.get(`/api/kb-admin/costs?days=${days}`),
        kbApi.get('/api/kb-admin/errors?limit=20'),
        kbApi.get('/api/kb-admin/weaviate-documents'),
        kbApi.get(`/api/kb-admin/activity-logs?hours=${hours}&limit=50&log_type=${activityFilter}`)
      ]);

      // Process health
      if (healthRes.status === 'fulfilled') {
        setHealth(healthRes.value.data);
      }

      // Process aggregate stats (includes documents and chat)
      if (statsRes.status === 'fulfilled') {
        const stats = statsRes.value.data;
        setAggregateStats(stats);
        
        // Extract document stats from combined stats
        if (stats.documents) {
          setDocumentStats({
            documents_processed: stats.documents.processed,
            total_chunks: stats.documents.chunks_created,
            total_tokens: stats.documents.tokens,
            total_cost_usd: stats.documents.cost_usd,
            period: stats.period,
            success_rate: stats.documents.success_rate ?? 100,
            successful: stats.documents.successful ?? 0,
            failed: stats.documents.failed ?? 0,
            avg_processing_time_ms: stats.documents.avg_processing_time_ms ?? 0
          });
        }
        
        // Extract chat stats from combined stats
        if (stats.chat) {
          setChatStats({
            total_sessions: stats.chat.sessions,
            total_messages: stats.chat.messages,
            total_tokens: stats.chat.tokens,
            total_cost_usd: stats.chat.cost_usd,
            avg_response_time_ms: stats.chat.avg_response_time_ms,
            period: stats.period
          });
        }
      }

      // Process chat stats (if needed separately)
      if (chatRes.status === 'fulfilled') {
        // Only override if not already set from combined stats
        if (!statsRes || statsRes.status !== 'fulfilled') {
          setChatStats(chatRes.value.data);
        }
      }

      // Process costs
      if (costsRes.status === 'fulfilled') {
        setCosts(costsRes.value.data);
      }

      // Process errors
      if (errorsRes.status === 'fulfilled') {
        setErrors(errorsRes.value.data.errors || []);
      }

      // Process activity logs
      if (activityRes.status === 'fulfilled') {
        setActivityLogs(activityRes.value.data.logs || []);
      }

      // Process Weaviate documents
      if (weaviateRes.status === 'fulfilled') {
        setWeaviateDocs(weaviateRes.value.data);
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
      const res = await kbApi.get(`/api/kb-admin/activity-logs?hours=${hours}&limit=50&log_type=${filter}`);
      const data = res.data;
      setActivityLogs(data.logs || []);
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
    const interval = setInterval(fetchData, 60000); // 1 minute
    return () => clearInterval(interval);
  }, [fetchData]);

  return (
    <div className="kb-analytics-page">
      <div className="kb-analytics-container">
        {/* Header */}
        <div className="kb-analytics-header-row">
          <div>
            <h1 className="kb-analytics-header-title">Knowledge Base Analytics</h1>
            <div className="kb-analytics-header-subtitle">
              Monitor document processing, chat usage, and system health
            </div>
          </div>
          <div className="kb-header-actions kb-analytics-header-actions">
            <ActionButton
              icon={Filter}
              className={`kb-analytics-header-action-button-filter ${showFilters ? 'is-active' : ''}`}
              onClick={() => setShowFilters(v => !v)}
            >
              {showFilters ? 'Hide Filters' : 'Show Filters'}
            </ActionButton>

            <ActionButton
              icon={RefreshCw}
              className="kb-analytics-header-action-button-refresh"
              onClick={fetchData}
              disabled={loading}
            >
              Refresh
            </ActionButton>
          </div>
        </div>

        {/* Filters Bar */}
        {showFilters && (
          <div className="kb-filters-bar">
            <div className="kb-section-filters">
              <span className="kb-filter-label">Show:</span>
              <button 
                className={`kb-section-toggle ${visibleSections.documents ? 'active' : ''}`}
                onClick={() => toggleSection('documents')}
              >
                Document Processing
              </button>
              <button 
                className={`kb-section-toggle ${visibleSections.chat ? 'active' : ''}`}
                onClick={() => toggleSection('chat')}
              >
                Chat Analytics
              </button>
              <button 
                className={`kb-section-toggle ${visibleSections.cost ? 'active' : ''}`}
                onClick={() => toggleSection('cost')}
              >
                Cost & Token
              </button>
              <button 
                className={`kb-section-toggle ${visibleSections.activity ? 'active' : ''}`}
                onClick={() => toggleSection('activity')}
              >
                Activity Logs
              </button>
            </div>
            <div className="kb-time-filter">
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
        )}

        {/* Error Banner */}
        {error && (
          <div className="kb-error-banner">
            <span>{error}</span>
            <button onClick={() => setError(null)}>×</button>
          </div>
        )}

        {/* Loading State */}
        {loading && !health && (
          <div className="kb-loading">
            <span>Loading analytics...</span>
          </div>
        )}

        {/* Main Content */}
        {!loading || health ? (
          <div className="kb-analytics-content">
          {/* Top Stats Cards */}
          <div className="kb-stat-cards">
            <StatCard
              label="Documents Processed"
              value={documentStats?.documents_processed || 0}
              subValue={`${documentStats?.total_chunks || 0} chunks`}
              color="blue"
            />
            <StatCard
              label="Chat Sessions"
              value={chatStats?.total_sessions || 0}
              subValue={`${chatStats?.total_messages || 0} messages`}
              color="green"
            />
            <StatCard
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
              label="Estimated Cost"
              value={costs?.total?.cost_usd ? `$${parseFloat(costs.total.cost_usd).toFixed(4)}` : '$0.00'}
              subValue={`period: ${costs?.period_days ? costs.period_days + 'd' : (costs?.period || '30d')}`}
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
    </div>
  );
};

export default KBAnalyticsPage;
