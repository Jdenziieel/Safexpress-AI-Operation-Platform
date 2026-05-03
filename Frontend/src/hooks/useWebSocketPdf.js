/**
 * WebSocket Hook for PDF Processing Real-Time Updates
 * Provides real-time progress updates for AI-powered PDF parsing
 * 
 * Usage:
 * const { isConnected, connectionId, progress, result, error, connect, disconnect } = useWebSocketPdf();
 * 
 * useEffect(() => { connect(); return () => disconnect(); }, []);
 * 
 * // Pass connectionId to PDF parse API to receive updates
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import { ACCESS_TOKEN } from '../token';

// WebSocket URL from environment variable
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8009/ws';

/**
 * Custom hook for WebSocket-based PDF processing updates
 * @param {Object} options - Hook options
 * @param {Function} options.onProgress - Callback for progress updates
 * @param {Function} options.onComplete - Callback when processing completes
 * @param {Function} options.onError - Callback for errors
 * @returns {Object} WebSocket PDF state and methods
 */
export const useWebSocketPdf = (options = {}) => {
    const { onProgress, onComplete, onError } = options;
    
    // Connection state
    const [isConnected, setIsConnected] = useState(false);
    const [connectionId, setConnectionId] = useState(null);
    const [connectionStatus, setConnectionStatus] = useState('disconnected');
    
    // Processing state
    const [currentJobId, setCurrentJobId] = useState(null);
    const [progress, setProgress] = useState(null);
    const [progressMessage, setProgressMessage] = useState('');
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);
    
    // Refs
    const wsRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const callbacksRef = useRef({ onProgress, onComplete, onError });
    
    // Keep callbacks updated
    useEffect(() => {
        callbacksRef.current = { onProgress, onComplete, onError };
    }, [onProgress, onComplete, onError]);
    
    /**
     * Handle incoming WebSocket messages for PDF processing
     */
    const handleMessage = useCallback((event) => {
        try {
            const data = JSON.parse(event.data);
            console.log('[WS PDF] Message received:', data.type, data);
            
            switch (data.type) {
                case 'connection_established':
                    // Server sends connection_id on connect
                    if (data.connection_id) {
                        setConnectionId(data.connection_id);
                        console.log('[WS PDF] Connection ID:', data.connection_id);
                    }
                    break;
                    
                case 'pdf_progress':
                    // Progress update from PDF processing
                    setCurrentJobId(data.job_id);
                    setProgress(data.progress);
                    setProgressMessage(data.message);
                    if (callbacksRef.current.onProgress) {
                        callbacksRef.current.onProgress(data);
                    }
                    break;
                    
                case 'pdf_complete':
                    // Processing completed with result
                    setCurrentJobId(data.job_id);
                    setProgress(100);
                    setProgressMessage('Complete!');
                    setResult(data.result);
                    if (callbacksRef.current.onComplete) {
                        callbacksRef.current.onComplete(data);
                    }
                    break;
                    
                case 'pdf_error':
                    // Processing failed
                    setCurrentJobId(data.job_id);
                    setProgress(null);
                    setProgressMessage('');
                    setError(data.error);
                    if (callbacksRef.current.onError) {
                        callbacksRef.current.onError(data);
                    }
                    break;
                    
                default:
                    // Ignore other message types (chat messages, etc.)
                    console.log('[WS PDF] Ignoring message type:', data.type);
            }
        } catch (e) {
            console.error('[WS PDF] Failed to parse message:', e);
        }
    }, []);
    
    /**
     * Connect to WebSocket server
     */
    const connect = useCallback(() => {
        // Don't reconnect if already connected
        if (wsRef.current?.readyState === WebSocket.OPEN || 
            wsRef.current?.readyState === WebSocket.CONNECTING) {
            console.log('[WS PDF] Already connected/connecting');
            return;
        }
        
        // Get authentication token
        const token = localStorage.getItem(ACCESS_TOKEN);
        if (!token) {
            setError('No authentication token available');
            setConnectionStatus('disconnected');
            return;
        }
        
        setConnectionStatus('connecting');
        setError(null);
        
        try {
            const wsUrl = `${WS_URL}?token=${encodeURIComponent(token)}`;
            console.log('[WS PDF] Connecting to:', WS_URL);
            
            wsRef.current = new WebSocket(wsUrl);

            wsRef.current.onopen = () => {
                console.log('[WS PDF] ✅ Connected successfully to:', WS_URL, 'at', new Date().toISOString());
                setIsConnected(true);
                setConnectionStatus('connected');
                setError(null);

                // Ask the server for our connection_id. The ws_connect
                // Lambda *tries* to push it during $connect, but API
                // Gateway frequently raises GoneException there because
                // the connection isn't fully registered yet. The
                // ws_default handler accepts {action:"register"} and
                // returns a connection_established message reliably
                // because the handshake is complete by then.
                try {
                    wsRef.current.send(JSON.stringify({ action: 'register' }));
                } catch (sendErr) {
                    console.warn('[WS PDF] Failed to send register message:', sendErr);
                }
            };

            wsRef.current.onmessage = handleMessage;
            
            wsRef.current.onerror = (event) => {
                console.error('[WS PDF] ❌ WebSocket error:', {
                    url: WS_URL,
                    readyState: wsRef.current?.readyState,
                    timestamp: new Date().toISOString(),
                    event
                });
                setError('WebSocket connection error');
            };
            
            wsRef.current.onclose = (event) => {
                const wasClean = event.code === 1000;
                console.log(`[WS PDF] 🔌 Disconnected — code=${event.code} reason="${event.reason || 'none'}" clean=${wasClean} at ${new Date().toISOString()}`);
                setIsConnected(false);
                setConnectionStatus('disconnected');
                setConnectionId(null);
                
                // Auto-reconnect after 3 seconds if not intentionally closed
                if (event.code !== 1000) {
                    reconnectTimeoutRef.current = setTimeout(() => {
                        console.log('[WS PDF] Attempting reconnect...');
                        connect();
                    }, 3000);
                }
            };
            
        } catch (e) {
            console.error('[WS PDF] Failed to connect:', e);
            setError(e.message);
            setConnectionStatus('disconnected');
        }
    }, [handleMessage]);
    
    /**
     * Disconnect from WebSocket
     */
    const disconnect = useCallback(() => {
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
        }
        
        if (wsRef.current) {
            wsRef.current.close(1000, 'User disconnect');
            wsRef.current = null;
        }
        
        setIsConnected(false);
        setConnectionStatus('disconnected');
        setConnectionId(null);
    }, []);
    
    /**
     * Reset processing state for a new job
     */
    const resetState = useCallback(() => {
        setCurrentJobId(null);
        setProgress(null);
        setProgressMessage('');
        setResult(null);
        setError(null);
    }, []);
    
    /**
     * Get the connection ID to send with API requests
     */
    const getConnectionId = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            return connectionId;
        }
        return null;
    }, [connectionId]);
    
    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
            }
            if (wsRef.current) {
                wsRef.current.close(1000, 'Component unmount');
            }
        };
    }, []);
    
    return {
        // Connection state
        isConnected,
        connectionId,
        connectionStatus,
        getConnectionId,
        
        // Processing state
        currentJobId,
        progress,
        progressMessage,
        result,
        error,
        
        // Methods
        connect,
        disconnect,
        resetState
    };
};

export default useWebSocketPdf;
