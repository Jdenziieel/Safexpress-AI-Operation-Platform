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
    // Set true by `cancelStreaming()`, cleared by the next
    // `sendAgentMessage()`. While true, inbound progress / paused /
    // complete / error frames for the canceled run are dropped on the
    // floor. The supervisor Lambda keeps running to completion (we have
    // no server-side cancel endpoint today) but its eventual frames are
    // ignored so the UI stays in the user-visible "stopped" state.
    const cancelledRef = useRef(false);

    // Pong-watchdog state. The 5-min heartbeat (see useEffect at the
    // bottom) bumps `lastPingSentAtRef`; every inbound `pong` frame
    // bumps `lastPongAtRef`. If a ping goes 30s without a matching
    // pong, the socket is considered silently dead — common after a
    // laptop sleep / network blip / NAT timeout where neither side
    // gets a TCP RST and `onclose` never fires. We then force-close
    // and rely on the existing exponential-backoff reconnect loop.
    //
    // Why this matters for the "5–15 min idle errors" the user reported:
    // without this watchdog, a silently-dead socket stays in
    // `readyState: OPEN` forever, so `sendAgentMessage()` cheerfully
    // calls `.send()` which fires `onerror` → `onclose`, but ONLY
    // after a long browser-controlled timeout (often 30–120s).
    // During that window the user sees a hung "Sending…" or a generic
    // "WebSocket is not connected" error. The watchdog cuts that
    // window down to 30s and triggers a clean reconnect proactively.
    const lastPingSentAtRef = useRef(0);
    const lastPongAtRef = useRef(0);
    // Pong-grace window. 30s comfortably covers cross-region API
    // Gateway round-trips (typically <500ms) and survives transient
    // packet loss without flapping the connection.
    const PONG_GRACE_MS = 30 * 1000;

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

        // If the user clicked Stop, swallow every per-run frame until the
        // next `sendAgentMessage()` clears the flag. Connection-level
        // frames (connection_established / pong) still flow so the
        // socket stays usable for the next message.
        if (
            cancelledRef.current &&
            data.type !== 'connection_established' &&
            data.type !== 'pong'
        ) {
            console.debug('[WS Agent] Dropping post-cancel frame:', data.type);
            return;
        }

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
                lastPongAtRef.current = Date.now();
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
            // Stale-socket recovery — common scenario after 5–15 min
            // idle when a laptop wakes up or the network blinked. The
            // old socket is in CLOSING/CLOSED but onclose may not have
            // fired yet (or fired during sleep and the reconnect
            // backoff hasn't kicked in). Kick off a fresh connect()
            // and surface a transient "Reconnecting…" state instead of
            // a hard error so the UI doesn't trap the user. We also
            // force-close any zombie wsRef so the auto-reconnect loop
            // takes over from a clean state.
            if (wsRef.current) {
                try { wsRef.current.close(4000, 'sendAgentMessage on stale socket'); }
                catch (_) { /* noop */ }
            }
            connect();
            setError({
                reason:  'NOT_CONNECTED',
                message: 'Reconnecting — your message was not sent. Please try again in a moment.',
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
        // request (progress, error, leftover cancel flag) would
        // otherwise leak into the new one. Clearing `cancelledRef` here
        // is what makes the user's next message immediately responsive
        // again after they hit Stop on the previous one.
        cancelledRef.current = false;
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
    }, [connect]);

    /**
     * Send a heartbeat ping. The supervisor responds with `{type:"pong"}`
     * via the kb-ws-default route — useful to keep the API Gateway idle
     * timeout from killing the socket between sparse user messages.
     *
     * Also stamps `lastPingSentAtRef` so the watchdog (in the heartbeat
     * useEffect) can detect missing pongs.
     */
    const ping = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            try {
                wsRef.current.send(JSON.stringify({ action: 'ping' }));
                lastPingSentAtRef.current = Date.now();
            } catch (_) {
                // Heartbeat failures are non-fatal — onclose will trigger reconnect.
            }
        }
    }, []);

    /**
     * Force-close the current socket without flagging it as intentional.
     * Used by the pong-watchdog and the visibility/online listeners when
     * we suspect the socket has gone silently dead. The existing
     * `onclose` handler will then kick off the exponential-backoff
     * reconnect loop.
     */
    const forceReconnect = useCallback((reason) => {
        if (!wsRef.current) return;
        console.warn(`[WS Agent] Force-reconnecting: ${reason}`);
        try {
            // Code 4000 is reserved for application use; not 1000 because
            // 1000 is treated as "intentional close" by the onclose
            // handler and would suppress reconnect.
            wsRef.current.close(4000, reason);
        } catch (_) {
            // Already closing/closed — onclose will still fire and
            // reconnect logic will pick it up.
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

    /**
     * Stop listening for the current in-flight `sendAgentMessage` run.
     *
     * Mirrors the SFXBot Stop-button UX. Implementation note: we do NOT
     * close the WebSocket here. AI Assistant uses one persistent socket
     * across many messages (unlike SFXBot which opens a fresh WS per
     * message), so closing would force a fresh handshake before the
     * user's next send. Instead we set a `cancelledRef` flag that
     * `handleMessage` honors — every per-run frame after this point
     * (progress / paused / complete / error) is dropped on the floor.
     *
     * Caveat the caller must understand: there is no server-side cancel
     * endpoint in supervisor-ws-chat today. The supervisor Lambda keeps
     * running to completion in the background and any tool actions that
     * already executed (sent emails, created docs, calendar events) are
     * NOT undone. This button stops the LISTENING, not the WORK. For
     * the AI Assistant this is acceptable because DANGEROUS tools pause
     * for explicit approval before executing anyway (see Sup
     * approval-tier model in agent_capabilities_v3.py).
     */
    const cancelStreaming = useCallback(() => {
        console.log('[WS Agent] 🛑 cancelStreaming() — dropping subsequent frames');
        cancelledRef.current = true;
        setIsStreaming(false);
        setStatusMessage('');
        setProgress(null);
    }, []);

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

    // Heartbeat + watchdog — keep the connection warm AND detect when
    // it has silently gone dead.
    //
    // Why two timers (heartbeat + watchdog) instead of one:
    //   - Heartbeat sends a ping every 5 minutes (API Gateway WS idle
    //     timeout is 10 min, so this stays well under).
    //   - Watchdog fires every 30s and checks "did we get a pong within
    //     PONG_GRACE_MS of the most recent ping?". If not, the socket
    //     is silently dead — typical after laptop sleep / network blip
    //     / NAT timeout. Force-reconnect proactively instead of waiting
    //     for the user's next sendAgentMessage() to discover the
    //     problem the hard way.
    useEffect(() => {
        if (!isConnected) return undefined;

        // Reset pong tracker on every fresh connection so the first
        // 30s window doesn't trip the watchdog before any ping has
        // been sent.
        lastPongAtRef.current = Date.now();
        lastPingSentAtRef.current = 0;

        const heartbeatId = setInterval(ping, 5 * 60 * 1000);
        const watchdogId = setInterval(() => {
            // Only judge the connection if we've sent a ping at least
            // once. The first 5 minutes after connect are pong-free
            // by design.
            const lastPing = lastPingSentAtRef.current;
            if (!lastPing) return;
            const lastPong = lastPongAtRef.current;
            const sincePing = Date.now() - lastPing;
            // Pong-grace expired AND the most recent pong is older
            // than the most recent ping → we sent a ping that never
            // came back. Force-reconnect.
            if (sincePing > PONG_GRACE_MS && lastPong < lastPing) {
                forceReconnect('pong-watchdog: no pong within grace window');
            }
        }, 30 * 1000);

        return () => {
            clearInterval(heartbeatId);
            clearInterval(watchdogId);
        };
    }, [isConnected, ping, forceReconnect]);

    // Tab/network resilience — when the user comes back from being
    // away (tab refocus, network reconnect), proactively check the
    // socket. Browsers sometimes hold a TCP connection open across
    // sleep/suspend without firing onclose, leading to "looks
    // connected but isn't" zombie sockets that only get exposed on
    // the next user action.
    useEffect(() => {
        if (typeof window === 'undefined') return undefined;

        const checkAndRecover = (trigger) => {
            // No socket → connect() owns the recovery (App.jsx wires
            // this on auth state). Nothing for us to do here.
            if (!wsRef.current) return;
            const rs = wsRef.current.readyState;
            // Healthy — leave it alone.
            if (rs === WebSocket.OPEN) {
                // Send an immediate ping so the watchdog has fresh
                // signal. If the socket is silently dead, the next
                // 30s tick will catch it.
                ping();
                return;
            }
            // CLOSING / CLOSED → onclose has either fired or is about
            // to; rely on the existing reconnect path. If for some
            // reason onclose got swallowed, force the close so the
            // handler runs.
            if (rs === WebSocket.CLOSING || rs === WebSocket.CLOSED) {
                forceReconnect(`${trigger}: socket in readyState=${rs}`);
            }
        };

        const onVisibility = () => {
            if (document.visibilityState === 'visible') {
                checkAndRecover('visibilitychange');
            }
        };
        const onOnline = () => checkAndRecover('online');
        const onFocus = () => checkAndRecover('focus');

        document.addEventListener('visibilitychange', onVisibility);
        window.addEventListener('online', onOnline);
        window.addEventListener('focus', onFocus);

        return () => {
            document.removeEventListener('visibilitychange', onVisibility);
            window.removeEventListener('online', onOnline);
            window.removeEventListener('focus', onFocus);
        };
    }, [ping, forceReconnect]);

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
        cancelStreaming,
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
