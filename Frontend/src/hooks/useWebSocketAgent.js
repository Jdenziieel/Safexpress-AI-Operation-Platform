/**
 * WebSocket Hook for the AI Assistant (supervisor-ws-chat) — `sendAgentMessage` route.
 *
 * Mirrors useWebSocketChat (which speaks `sendMessage` for KB chat) but
 * targets the AI Assistant supervisor that lives on the same WebSocket API
 * (`wss://<api-id>.execute-api.<region>.amazonaws.com/prod`) under a
 * different action key.
 *
 * Protocol (see websocket.md §5):
 *
 *   Client -> Server:
 *     { action: "sendAgentMessage",
 *       thread_id: "<existing-thread-id>",
 *       message: "...",
 *       uploaded_file: null | { filename, content_type, s3_key } }
 *
 *   Server -> Client (all carry a `type`):
 *     - status    : pipeline progress (analyzing | planning | executing | ...)
 *     - progress  : per-step orchestrator progress
 *                   { type, data: { step, total_steps, agent, tool, status }, thread_id, timestamp }
 *     - paused    : workflow paused for human approval
 *                   { type, thread_id, action_id, response, ready_for_execution, elapsed_ms }
 *     - complete  : workflow finished (or chat-only response)
 *                   { type, thread_id, response, ready_for_execution, status: "success", elapsed_ms }
 *     - error     : any failure (UNAUTHORIZED, QUOTA_EXCEEDED, BRAIN_IMPORT_FAILED, ...)
 *     - pong      : reply to { action: "ping" } heartbeat
 *
 * Usage:
 *   const agent = useWebSocketAgent();
 *   agent.connect();
 *   agent.onComplete((msg) => { ... msg.response ... });
 *   agent.onProgress((data) => { ... });
 *   agent.sendAgentMessage(threadId, "what's on my calendar today?");
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import { ACCESS_TOKEN } from '../token';

// Same WebSocket API as KB chat — the route key is what differs.
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8009/ws';

// Matches the AA-lambda spec: `error.reason` codes that callers commonly key
// off of. Re-exported for ergonomic switch statements at the call site.
export const AGENT_ERROR_REASONS = Object.freeze({
    UNAUTHORIZED:        'UNAUTHORIZED',
    QUOTA_EXCEEDED:      'QUOTA_EXCEEDED',
    UNKNOWN_ACTION:      'UNKNOWN_ACTION',
    BRAIN_IMPORT_FAILED: 'BRAIN_IMPORT_FAILED',
});

export const useWebSocketAgent = () => {
    // Connection state
    const [isConnected, setIsConnected] = useState(false);
    const [connectionStatus, setConnectionStatus] = useState('disconnected');
    const [connectionId, setConnectionId] = useState(null);

    // Run state (one in-flight `sendAgentMessage` at a time per socket)
    const [isStreaming, setIsStreaming] = useState(false);
    const [statusMessage, setStatusMessage] = useState('');
    const [progress, setProgress] = useState(null);
    const [error, setError] = useState(null);
    const [lastResponse, setLastResponse] = useState(null);

    // Refs
    const wsRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const reconnectAttempts = useRef(0);
    const maxReconnectAttempts = 5;
    const intentionalCloseRef = useRef(false);

    // Caller-supplied callbacks. Stored in refs so we don't reconnect on
    // every render when callers redefine handlers inline.
    const handlersRef = useRef({
        onStatus:   null,
        onProgress: null,
        onPaused:   null,
        onComplete: null,
        onError:    null,
        onPong:     null,
    });

    /**
     * Route an inbound frame to the right state setter + caller callback.
     * Kept tiny and synchronous — no awaits — so React batches the resulting
     * setState calls inside the same microtask.
     */
    const handleMessage = useCallback((data) => {
        const handlers = handlersRef.current;

        switch (data.type) {
            case 'connection_established':
                if (data.connection_id) setConnectionId(data.connection_id);
                break;

            case 'status':
                setStatusMessage(data.message || data.status || '');
                if (handlers.onStatus) handlers.onStatus(data);
                break;

            case 'progress': {
                // Backend shape (per spec): { type, data: {...}, thread_id, timestamp }
                // Frontend prefers the inner `data` payload but tolerates
                // flat shapes for forward-compat.
                const payload = data.data || data;
                setProgress(payload);
                if (handlers.onProgress) handlers.onProgress(payload, data);
                break;
            }

            case 'paused':
                // Workflow paused for HITL approval. Streaming is "done"
                // from the socket's perspective — caller should fetch
                // pending actions and surface the approval UI.
                setIsStreaming(false);
                setStatusMessage('Awaiting approval…');
                if (handlers.onPaused) handlers.onPaused(data);
                break;

            case 'complete':
                setIsStreaming(false);
                setStatusMessage('');
                setProgress(null);
                setLastResponse(data);
                if (handlers.onComplete) handlers.onComplete(data);
                break;

            case 'error':
                setIsStreaming(false);
                setStatusMessage('');
                setProgress(null);
                // Surface the structured error so callers can branch on
                // `reason` (UNAUTHORIZED / QUOTA_EXCEEDED / BRAIN_IMPORT_FAILED ...).
                setError({
                    reason:  data.reason || 'UNKNOWN',
                    message: data.message || 'Agent request failed',
                    raw:     data,
                });
                if (handlers.onError) handlers.onError(data);
                break;

            case 'pong':
                if (handlers.onPong) handlers.onPong(data);
                break;

            default:
                // Forward-compat: silently ignore unknown frame types
                // rather than throwing — the supervisor may add new ones.
                console.debug('[WS Agent] Ignoring unknown message type:', data.type, data);
        }
    }, []);

    /**
     * Open the socket. Idempotent — multiple calls while OPEN/CONNECTING
     * are no-ops. Auth token is read fresh on each connect (so a refreshed
     * JWT picked up by the axios interceptor flows through here too, on
     * the next reconnect).
     */
    const connect = useCallback(() => {
        if (
            wsRef.current?.readyState === WebSocket.OPEN ||
            wsRef.current?.readyState === WebSocket.CONNECTING
        ) {
            return;
        }

        const token = localStorage.getItem(ACCESS_TOKEN);
        if (!token) {
            setError({ reason: 'NO_TOKEN', message: 'No authentication token available' });
            setConnectionStatus('disconnected');
            return;
        }

        intentionalCloseRef.current = false;
        setConnectionStatus('connecting');
        setError(null);

        try {
            const url = `${WS_URL}?token=${encodeURIComponent(token)}`;
            console.log('[WS Agent] Connecting to', WS_URL);
            wsRef.current = new WebSocket(url);

            wsRef.current.onopen = () => {
                console.log('[WS Agent] ✅ Connected');
                setIsConnected(true);
                setConnectionStatus('connected');
                reconnectAttempts.current = 0;

                // Ask for connection_id explicitly. ws_connect tries to
                // push it during $connect but API Gateway often fails
                // there (race with the WS handshake). ws_default's
                // `register` action is the reliable path.
                try {
                    wsRef.current.send(JSON.stringify({ action: 'register' }));
                } catch (_) {
                    // Ignored — onopen-time send failures are rare and
                    // the next sendAgentMessage will surface real issues.
                }
            };

            wsRef.current.onmessage = (event) => {
                try {
                    handleMessage(JSON.parse(event.data));
                } catch (e) {
                    console.error('[WS Agent] Failed to parse frame:', e, event.data);
                }
            };

            wsRef.current.onerror = (ev) => {
                console.error('[WS Agent] ❌ Socket error:', {
                    url: WS_URL,
                    readyState: wsRef.current?.readyState,
                    timestamp: new Date().toISOString(),
                });
                // The browser only fires a generic Event here; the real
                // close reason comes via onclose. Don't set isStreaming
                // false yet — let onclose handle the terminal state.
                setError((prev) =>
                    prev ?? { reason: 'SOCKET_ERROR', message: 'WebSocket connection error' }
                );
            };

            wsRef.current.onclose = (event) => {
                console.log(
                    `[WS Agent] 🔌 Disconnected — code=${event.code} reason="${event.reason || 'none'}"`
                );
                setIsConnected(false);
                setConnectionStatus('disconnected');
                setConnectionId(null);
                setIsStreaming(false);

                // Auto-reconnect with exponential backoff unless the close
                // was intentional (user logged out, component unmounted,
                // explicit disconnect()).
                if (
                    !intentionalCloseRef.current &&
                    event.code !== 1000 &&
                    reconnectAttempts.current < maxReconnectAttempts
                ) {
                    const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 30000);
                    reconnectTimeoutRef.current = setTimeout(() => {
                        reconnectAttempts.current += 1;
                        connect();
                    }, delay);
                }
            };
        } catch (e) {
            console.error('[WS Agent] Failed to open socket:', e);
            setError({ reason: 'CONNECT_FAILED', message: e.message });
            setConnectionStatus('disconnected');
        }
    }, [handleMessage]);

    /**
     * Send a sendAgentMessage frame.
     *
     * Returns `true` if the frame was queued on the socket, `false` if
     * something blocked it (no socket / no thread_id / no message). The
     * actual response arrives asynchronously via the registered callbacks.
     */
    const sendAgentMessage = useCallback((threadId, message, uploadedFile = null) => {
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
            setError({
                reason:  'NOT_CONNECTED',
                message: 'WebSocket is not connected. Please wait for connection.',
            });
            return false;
        }
        if (!threadId) {
            setError({
                reason:  'NO_THREAD_ID',
                message: 'thread_id is required — create one with POST /threads first.',
            });
            return false;
        }
        if (typeof message !== 'string' || !message.trim()) {
            setError({ reason: 'EMPTY_MESSAGE', message: 'Message cannot be empty' });
            return false;
        }

        // Reset per-request state. Anything leftover from a previous
        // request (progress, error) would otherwise leak into the new one.
        setIsStreaming(true);
        setStatusMessage('Sending…');
        setProgress(null);
        setError(null);
        setLastResponse(null);

        const payload = {
            action:        'sendAgentMessage',
            thread_id:     threadId,
            message:       message.trim(),
            uploaded_file: uploadedFile,
        };

        try {
            wsRef.current.send(JSON.stringify(payload));
            return true;
        } catch (e) {
            console.error('[WS Agent] Failed to send:', e);
            setError({ reason: 'SEND_FAILED', message: e.message });
            setIsStreaming(false);
            return false;
        }
    }, []);

    /**
     * Send a heartbeat ping. The supervisor responds with `{type:"pong"}`
     * via the kb-ws-default route — useful to keep the API Gateway idle
     * timeout from killing the socket between sparse user messages.
     */
    const ping = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            try {
                wsRef.current.send(JSON.stringify({ action: 'ping' }));
            } catch (_) {
                // Heartbeat failures are non-fatal — onclose will trigger reconnect.
            }
        }
    }, []);

    const disconnect = useCallback(() => {
        intentionalCloseRef.current = true;

        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = null;
        }

        if (wsRef.current) {
            try {
                wsRef.current.close(1000, 'User disconnect');
            } catch (_) {
                // Already-closed sockets throw; nothing to do.
            }
            wsRef.current = null;
        }

        setIsConnected(false);
        setConnectionStatus('disconnected');
        setConnectionId(null);
        setIsStreaming(false);
        reconnectAttempts.current = 0;
    }, []);

    const clearError = useCallback(() => setError(null), []);

    // Callback registration helpers — stored in a ref so updating handlers
    // doesn't tear down the socket.
    const onStatus   = useCallback((cb) => { handlersRef.current.onStatus   = cb; }, []);
    const onProgress = useCallback((cb) => { handlersRef.current.onProgress = cb; }, []);
    const onPaused   = useCallback((cb) => { handlersRef.current.onPaused   = cb; }, []);
    const onComplete = useCallback((cb) => { handlersRef.current.onComplete = cb; }, []);
    const onError    = useCallback((cb) => { handlersRef.current.onError    = cb; }, []);
    const onPong     = useCallback((cb) => { handlersRef.current.onPong     = cb; }, []);

    // Cleanup on unmount — close the socket, clear timers.
    useEffect(() => {
        return () => {
            intentionalCloseRef.current = true;
            if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
            if (wsRef.current) {
                try { wsRef.current.close(1000, 'Component unmount'); } catch (_) { /* noop */ }
            }
        };
    }, []);

    // Heartbeat — keep the connection warm. API Gateway WebSocket APIs
    // idle out at 10 minutes; we ping every 5 to stay well under.
    useEffect(() => {
        if (!isConnected) return undefined;
        const id = setInterval(ping, 5 * 60 * 1000);
        return () => clearInterval(id);
    }, [isConnected, ping]);

    return {
        // Connection state
        isConnected,
        connectionStatus,
        connectionId,

        // Run state
        isStreaming,
        statusMessage,
        progress,
        error,
        lastResponse,

        // Actions
        connect,
        disconnect,
        sendAgentMessage,
        ping,
        clearError,

        // Event subscription
        onStatus,
        onProgress,
        onPaused,
        onComplete,
        onError,
        onPong,
    };
};

export default useWebSocketAgent;
