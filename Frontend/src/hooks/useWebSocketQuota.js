/**
 * WebSocket Quota Hook — Real-Time Token Quota Updates
 * 
 * Replaces polling-based quota fetching with a WebSocket-driven approach.
 * 
 * How it works:
 *  1. Opens a WebSocket connection to the shared WS endpoint (VITE_WS_URL)
 *  2. On successful connection, performs an initial HTTP fetch for quota data
 *  3. Listens for server-pushed `quota_update` messages (future-proof)
 *  4. Listens for `quota:refresh` CustomEvents dispatched by chat/PDF components
 *     when tokens are consumed — triggers an immediate HTTP refresh
 *  5. Falls back to slow HTTP polling (2 min) ONLY when WebSocket is disconnected
 *  6. Comprehensive [WS Quota] prefixed logging for easy debugging
 * 
 * Usage:
 *   const { quotaData, loading, error, isConnected, refresh } = useWebSocketQuota(userId, userName);
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import { ACCESS_TOKEN } from '../token';
import { quotaApi } from '../api';

// WebSocket URL from environment
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8009/ws';

// Timing constants
const FALLBACK_POLL_INTERVAL = 120_000;   // 2 min — only when WS is down
const WS_HEARTBEAT_INTERVAL  = 60_000;    // 1 min — keep-alive ping
const RECONNECT_BASE_DELAY   = 2_000;     // 2 s — initial reconnect delay
const MAX_RECONNECT_ATTEMPTS = 8;         // max retries before giving up
const DEBOUNCE_REFRESH_MS    = 500;       // first fetch — fast feedback, still coalesces rapid events
// Second fetch — safety net for the supervisor-ws-chat flow where
// `_report_quota_usage()` is fire-and-forget into a thread pool and
// the WS `complete` push can race ahead of the quota-report HTTP
// landing in UserQuotas. By 3.5s the supervisor's
// flush_pending_quota_reports(timeout=3.0) has either succeeded or
// timed out, so a fetch at this point is guaranteed to see the
// final state (or the same stale state if the report was lost,
// which is no worse than before).
const FOLLOWUP_REFRESH_MS    = 3_500;

/**
 * @param {string} userId   — UUID of the current user
 * @param {string|null} userName — display name (sent as query param)
 */
export const useWebSocketQuota = (userId, userName) => {
  // ── State ──────────────────────────────────────────────────────────────
  const [quotaData, setQuotaData]           = useState(null);
  const [loading, setLoading]               = useState(true);
  const [error, setError]                   = useState(null);
  const [isConnected, setIsConnected]       = useState(false);
  const [connectionStatus, setConnectionStatus] = useState('disconnected'); // disconnected | connecting | connected

  // ── Refs ───────────────────────────────────────────────────────────────
  const wsRef                = useRef(null);
  const reconnectTimeout     = useRef(null);
  const reconnectAttempts    = useRef(0);
  const heartbeatInterval    = useRef(null);
  const fallbackPollInterval = useRef(null);
  const debounceTimer        = useRef(null);
  const followupTimer        = useRef(null);
  const isMounted            = useRef(true);

  // ── Logging helper ─────────────────────────────────────────────────────
  const log = useCallback((emoji, ...args) => {
    console.log(`${emoji} [WS Quota]`, ...args);
  }, []);

  const logWarn = useCallback((...args) => {
    console.warn('⚠️ [WS Quota]', ...args);
  }, []);

  const logError = useCallback((...args) => {
    console.error('❌ [WS Quota]', ...args);
  }, []);

  // ── HTTP Fetch (used on connect + as fallback) ─────────────────────────
  const fetchQuotaHTTP = useCallback(async (reason = 'unknown') => {
    if (!userId || userId === 'default_user') {
      log('⏭️', 'Skipping fetch — no valid userId');
      return;
    }

    log('🔄', `Fetching quota via HTTP (reason: ${reason}) for user=${userId}`);

    try {
      const params = new URLSearchParams();
      if (userName) params.append('name', userName);

      const url = `/api/quota/balance/${userId}${params.toString() ? '?' + params.toString() : ''}`;
      const response = await quotaApi.get(url);

      if (!isMounted.current) return;

      setQuotaData(response.data);
      setError(null);
      log('✅', 'Quota data received:', {
        usage: response.data.current_usage,
        limit: response.data.monthly_limit,
        pct: response.data.percentage_used?.toFixed(1) + '%',
        tier: response.data.tier,
      });
    } catch (err) {
      if (!isMounted.current) return;

      if (err.response?.status === 404) {
        logWarn('User not onboarded in quota system (404)');
        setError('Quota not configured');
      } else {
        logError('HTTP fetch failed:', err.message, err.response?.status);
        setError('Unable to load quota');
      }
    } finally {
      if (isMounted.current) setLoading(false);
    }
  }, [userId, userName, log, logWarn, logError]);

  // ── Debounced refresh — fast first fetch + safety-net follow-up ───────
  // Why two fetches instead of one slow debounce?
  //   The supervisor (AA-lambda/.../supervisor-ws-chat) emits the
  //   `complete` WebSocket message BEFORE its async quota-report pool
  //   has finished POSTing to /quota/report. A single 1500ms debounce
  //   was either too slow for "real-time" UX or too fast to see the
  //   freshly-written quota — depending on network jitter. The new
  //   shape gives the user instant visual feedback (500ms) and a
  //   guaranteed-fresh re-read once the backend's flush window has
  //   elapsed (3500ms). Coalescing still works because each new
  //   event clears both timers and re-arms them.
  const debouncedRefresh = useCallback((reason = 'event') => {
    if (debounceTimer.current) clearTimeout(debounceTimer.current);
    if (followupTimer.current) clearTimeout(followupTimer.current);

    debounceTimer.current = setTimeout(() => {
      fetchQuotaHTTP(reason);
      debounceTimer.current = null;
    }, DEBOUNCE_REFRESH_MS);

    followupTimer.current = setTimeout(() => {
      fetchQuotaHTTP(`${reason}-followup`);
      followupTimer.current = null;
    }, FOLLOWUP_REFRESH_MS);
  }, [fetchQuotaHTTP]);

  // ── Public manual refresh ──────────────────────────────────────────────
  const refresh = useCallback(() => {
    log('🔃', 'Manual refresh triggered');
    fetchQuotaHTTP('manual');
  }, [fetchQuotaHTTP, log]);

  // ── Fallback polling (only when WS is down) ────────────────────────────
  const startFallbackPolling = useCallback(() => {
    if (fallbackPollInterval.current) return; // already running
    log('⏱️', `Starting fallback HTTP polling every ${FALLBACK_POLL_INTERVAL / 1000}s`);
    fallbackPollInterval.current = setInterval(() => {
      fetchQuotaHTTP('fallback-poll');
    }, FALLBACK_POLL_INTERVAL);
  }, [fetchQuotaHTTP, log]);

  const stopFallbackPolling = useCallback(() => {
    if (fallbackPollInterval.current) {
      log('⏱️', 'Stopping fallback HTTP polling');
      clearInterval(fallbackPollInterval.current);
      fallbackPollInterval.current = null;
    }
  }, [log]);

  // ── WebSocket Heartbeat ────────────────────────────────────────────────
  const startHeartbeat = useCallback(() => {
    if (heartbeatInterval.current) clearInterval(heartbeatInterval.current);
    heartbeatInterval.current = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        try {
          wsRef.current.send(JSON.stringify({ action: 'ping' }));
          log('💓', 'Heartbeat ping sent');
        } catch (e) {
          logWarn('Heartbeat send failed:', e.message);
        }
      }
    }, WS_HEARTBEAT_INTERVAL);
  }, [log, logWarn]);

  const stopHeartbeat = useCallback(() => {
    if (heartbeatInterval.current) {
      clearInterval(heartbeatInterval.current);
      heartbeatInterval.current = null;
    }
  }, []);

  // ── Handle incoming WS messages ────────────────────────────────────────
  const handleMessage = useCallback((event) => {
    try {
      const data = JSON.parse(event.data);

      // API Gateway may send error responses without a 'type' field
      // (e.g. "Internal server error" from unhandled routes). Ignore them.
      if (!data.type) {
        if (data.message === 'Internal server error') {
          // Silently ignore — this is the $default route responding to heartbeat
          return;
        }
        log('📨', 'Message with no type:', data);
        return;
      }

      switch (data.type) {
        case 'connection_established':
          log('🤝', 'Server confirmed connection, id:', data.connection_id);
          // Connection is live — do initial quota fetch
          fetchQuotaHTTP('ws-connected');
          break;

        case 'quota_update':
          // Server-pushed quota data (future backend enhancement)
          log('📊', 'Server pushed quota update');
          if (isMounted.current) {
            setQuotaData(data.quota || data);
            setError(null);
          }
          break;

        case 'complete':
        case 'done':
          // Chat message completed — tokens were consumed
          log('💬', `Chat ${data.type} received — tokens_used=${data.tokens_used || data.tokens || '?'}. Refreshing quota…`);
          debouncedRefresh('chat-complete');
          break;

        case 'pong':
          // Heartbeat acknowledged — connection is alive
          break;

        case 'error':
          logWarn('Server error message:', data.message || data.content);
          break;

        default:
          // Ignore message types meant for other handlers (token, status, pdf_*, etc.)
          break;
      }
    } catch (e) {
      logWarn('Failed to parse WS message:', e.message);
    }
  }, [fetchQuotaHTTP, debouncedRefresh, log, logWarn]);

  // ── Connect to WebSocket ───────────────────────────────────────────────
  const connect = useCallback(() => {
    // Guard: already open or connecting
    if (wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING) {
      log('🔌', 'Already connected/connecting — skipping');
      return;
    }

    const token = localStorage.getItem(ACCESS_TOKEN);
    if (!token) {
      logWarn('No auth token — cannot connect WebSocket');
      setConnectionStatus('disconnected');
      startFallbackPolling();
      return;
    }

    log('🔌', `Connecting to ${WS_URL} (attempt ${reconnectAttempts.current + 1}/${MAX_RECONNECT_ATTEMPTS})`);
    setConnectionStatus('connecting');

    try {
      const wsUrl = `${WS_URL}?token=${encodeURIComponent(token)}`;
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      // ── onopen ──
      ws.onopen = () => {
        if (!isMounted.current) return;
        log('✅', 'WebSocket connected successfully');
        setIsConnected(true);
        setConnectionStatus('connected');
        setError(null);
        reconnectAttempts.current = 0;

        // Stop fallback polling — WS is live
        stopFallbackPolling();
        // Start heartbeat
        startHeartbeat();
        // Initial quota fetch (in case server doesn't send connection_established)
        fetchQuotaHTTP('ws-open');
      };

      // ── onmessage ──
      ws.onmessage = handleMessage;

      // ── onerror ──
      ws.onerror = (evt) => {
        logError('WebSocket error event:', {
          url: WS_URL,
          readyState: ws.readyState,
          timestamp: new Date().toISOString(),
        });
        if (isMounted.current) {
          setConnectionStatus('disconnected');
        }
      };

      // ── onclose ──
      ws.onclose = (evt) => {
        if (!isMounted.current) return;

        const wasClean = evt.code === 1000;
        log('🔌', `WebSocket closed — code=${evt.code} reason="${evt.reason || 'none'}" clean=${wasClean}`);

        setIsConnected(false);
        setConnectionStatus('disconnected');
        stopHeartbeat();

        // Start fallback polling immediately
        startFallbackPolling();

        // Auto-reconnect with exponential backoff (unless intentional close)
        if (!wasClean && reconnectAttempts.current < MAX_RECONNECT_ATTEMPTS) {
          const delay = Math.min(
            RECONNECT_BASE_DELAY * Math.pow(2, reconnectAttempts.current),
            60_000
          );
          log('🔄', `Scheduling reconnect in ${(delay / 1000).toFixed(1)}s (attempt ${reconnectAttempts.current + 1}/${MAX_RECONNECT_ATTEMPTS})`);
          reconnectTimeout.current = setTimeout(() => {
            reconnectAttempts.current++;
            connect();
          }, delay);
        } else if (reconnectAttempts.current >= MAX_RECONNECT_ATTEMPTS) {
          logWarn(`Max reconnect attempts (${MAX_RECONNECT_ATTEMPTS}) reached — staying on fallback polling`);
        }
      };
    } catch (e) {
      logError('Failed to create WebSocket:', e.message);
      setConnectionStatus('disconnected');
      if (isMounted.current) startFallbackPolling();
    }
  }, [handleMessage, fetchQuotaHTTP, startFallbackPolling, stopFallbackPolling, startHeartbeat, stopHeartbeat, log, logWarn, logError]);

  // ── Disconnect (clean) ─────────────────────────────────────────────────
  const disconnect = useCallback(() => {
    log('🔌', 'Disconnecting (clean)');

    if (reconnectTimeout.current) {
      clearTimeout(reconnectTimeout.current);
      reconnectTimeout.current = null;
    }

    stopHeartbeat();
    stopFallbackPolling();

    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
      debounceTimer.current = null;
    }

    if (followupTimer.current) {
      clearTimeout(followupTimer.current);
      followupTimer.current = null;
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'Component unmounted');
      wsRef.current = null;
    }

    reconnectAttempts.current = 0;
    setIsConnected(false);
    setConnectionStatus('disconnected');
  }, [stopHeartbeat, stopFallbackPolling, log]);

  // ── Listen for cross-component `quota:refresh` events ──────────────────
  useEffect(() => {
    const handler = (evt) => {
      const reason = evt.detail?.reason || 'custom-event';
      const tokensUsed = evt.detail?.tokens_used;
      log('📡', `Received quota:refresh event — reason=${reason}${tokensUsed ? ` tokens=${tokensUsed}` : ''}`);
      debouncedRefresh(reason);
    };

    window.addEventListener('quota:refresh', handler);
    log('👂', 'Listening for quota:refresh events');

    return () => {
      window.removeEventListener('quota:refresh', handler);
    };
  }, [debouncedRefresh, log]);

  // ── Lifecycle: connect on mount, disconnect on unmount ─────────────────
  useEffect(() => {
    isMounted.current = true;

    if (userId && userId !== 'default_user') {
      log('🚀', `Initializing for user=${userId}`);
      connect();
    } else {
      log('⏭️', 'No userId yet — waiting');
      // Still do initial HTTP fetch for data
      fetchQuotaHTTP('initial-no-ws');
    }

    return () => {
      isMounted.current = false;
      disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId]);

  // ── Return ─────────────────────────────────────────────────────────────
  return {
    quotaData,
    loading,
    error,
    isConnected,
    connectionStatus,
    refresh,
  };
};

// ── Helper: dispatch quota:refresh from any component ──────────────────────
export const dispatchQuotaRefresh = (reason = 'unknown', tokensUsed = null) => {
  console.log(`📡 [Quota Event] Dispatching quota:refresh — reason=${reason}${tokensUsed ? ` tokens=${tokensUsed}` : ''}`);
  window.dispatchEvent(
    new CustomEvent('quota:refresh', {
      detail: { reason, tokens_used: tokensUsed },
    })
  );
};

export default useWebSocketQuota;
