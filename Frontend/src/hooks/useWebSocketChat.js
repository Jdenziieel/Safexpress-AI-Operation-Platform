/**
 * WebSocket Chat Hook for Real-Time Streaming
 * Provides streaming AI responses like ChatGPT
 * 
 * Usage:
 * const { isConnected, isStreaming, streamingText, sendMessage, connect } = useWebSocketChat();
 * 
 * useEffect(() => { connect(); }, [connect]);
 * 
 * const handleSend = () => {
 *   sendMessage('What is SafeXpress?', sessionId);
 * };
 */
import { useState, useRef, useCallback, useEffect } from 'react';
import { ACCESS_TOKEN } from '../token';

// WebSocket URL from environment variable
const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8009/ws';

/**
 * Custom hook for WebSocket-based streaming chat
 * @returns {Object} WebSocket chat state and methods
 */
export const useWebSocketChat = () => {
    // Connection state
    const [isConnected, setIsConnected] = useState(false);
    const [connectionStatus, setConnectionStatus] = useState('disconnected'); // disconnected, connecting, connected
    
    // Streaming state
    const [isStreaming, setIsStreaming] = useState(false);
    const [streamingText, setStreamingText] = useState('');
    const [streamingStatus, setStreamingStatus] = useState(''); // processing, generating, etc.
    
    // Response data
    const [sources, setSources] = useState([]);
    const [error, setError] = useState(null);
    const [lastSessionId, setLastSessionId] = useState(null);
    
    // Refs
    const wsRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const reconnectAttempts = useRef(0);
    const maxReconnectAttempts = 5;
    const messageCallbackRef = useRef(null);
    const errorCallbackRef = useRef(null);
    
    /**
     * Connect to WebSocket server
     */
    const connect = useCallback(() => {
        // Don't reconnect if already connected or connecting
        if (wsRef.current?.readyState === WebSocket.OPEN || 
            wsRef.current?.readyState === WebSocket.CONNECTING) {
            console.log('WebSocket already connected/connecting');
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
        
        try {
            const wsUrl = `${WS_URL}?token=${encodeURIComponent(token)}`;
            console.log('🔌 Connecting to WebSocket:', WS_URL);
            
            wsRef.current = new WebSocket(wsUrl);
            
            // Connection opened
            wsRef.current.onopen = () => {
                console.log('✅ WebSocket connected successfully');
                setIsConnected(true);
                setConnectionStatus('connected');
                setError(null);
                reconnectAttempts.current = 0;
            };
            
            // Message received
            wsRef.current.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    handleMessage(data);
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                }
            };
            
            // Connection error
            wsRef.current.onerror = (error) => {
                console.error('❌ [WS Chat] WebSocket error:', {
                    url: WS_URL,
                    readyState: wsRef.current?.readyState,
                    timestamp: new Date().toISOString(),
                    error
                });
                setError('Connection error occurred');
                setConnectionStatus('disconnected');
            };
            
            // Connection closed
            wsRef.current.onclose = (event) => {
                console.log(`🔌 WebSocket disconnected (code: ${event.code}, reason: ${event.reason})`);
                setIsConnected(false);
                setConnectionStatus('disconnected');
                
                // Auto-reconnect if not intentional close (code 1000)
                if (event.code !== 1000 && reconnectAttempts.current < maxReconnectAttempts) {
                    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
                    console.log(`🔄 Reconnecting in ${delay/1000}s (attempt ${reconnectAttempts.current + 1}/${maxReconnectAttempts})`);
                    
                    reconnectTimeoutRef.current = setTimeout(() => {
                        reconnectAttempts.current++;
                        connect();
                    }, delay);
                }
            };
            
        } catch (e) {
            console.error('Failed to create WebSocket connection:', e);
            setError(e.message);
            setConnectionStatus('disconnected');
        }
    }, []);
    
    /**
     * Handle incoming WebSocket messages
     */
    const handleMessage = useCallback((data) => {
        console.log('📨 WS Message:', data.type, data);
        
        switch (data.type) {
            case 'status':
                // Status updates during processing
                setStreamingStatus(data.message || data.status);
                if (data.sources) {
                    setSources(data.sources);
                }
                break;
                
            case 'token':
                // Streaming token - append to text
                setStreamingText(prev => prev + data.content);
                setStreamingStatus('generating');
                if (data.session_id) {
                    setLastSessionId(data.session_id);
                }
                break;
                
            case 'complete':
                // Response complete
                setIsStreaming(false);
                setStreamingStatus('');
                
                if (data.session_id) {
                    setLastSessionId(data.session_id);
                }
                
                // Call the message complete callback
                if (messageCallbackRef.current) {
                    messageCallbackRef.current({
                        role: 'assistant',
                        content: data.full_response,
                        sources: data.sources || sources,
                        tokens_used: data.tokens_used,
                        session_id: data.session_id,
                        model: data.model
                    });
                }
                
                // Clear streaming text after callback
                setStreamingText('');
                break;
                
            case 'error':
                // Error message
                setError(data.message);
                setIsStreaming(false);
                setStreamingStatus('');
                
                if (errorCallbackRef.current) {
                    errorCallbackRef.current(data.message);
                }
                break;
                
            default:
                console.warn('Unknown WebSocket message type:', data.type);
        }
    }, [sources]);
    
    /**
     * Disconnect from WebSocket server
     */
    const disconnect = useCallback(() => {
        // Clear any pending reconnection
        if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = null;
        }
        
        // Close the connection
        if (wsRef.current) {
            wsRef.current.close(1000, 'User disconnected');
            wsRef.current = null;
        }
        
        setIsConnected(false);
        setConnectionStatus('disconnected');
        reconnectAttempts.current = 0;
    }, []);
    
    /**
     * Send a chat message via WebSocket
     * @param {string} message - The user's message
     * @param {string|null} sessionId - Optional session ID for conversation continuity
     * @param {Object} options - Optional configuration (temperature, max_tokens, etc.)
     * @returns {boolean} - Whether the message was sent successfully
     */
    const sendMessage = useCallback((message, sessionId = null, options = {}) => {
        // Check connection
        if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
            setError('WebSocket is not connected. Please wait for connection.');
            return false;
        }
        
        // Validate message
        if (!message || typeof message !== 'string' || !message.trim()) {
            setError('Message cannot be empty');
            return false;
        }
        
        // Reset state for new message
        setIsStreaming(true);
        setStreamingText('');
        setStreamingStatus('processing');
        setError(null);
        setSources([]);
        
        // Build payload
        const payload = {
            action: 'sendMessage',
            message: message.trim(),
            session_id: sessionId || lastSessionId,
            options: {
                temperature: options.temperature ?? 0.7,
                max_tokens: options.max_tokens ?? 2000,
                search_top_k: options.search_top_k ?? 5,
                model: options.model ?? 'gpt-4o-mini',
                ...options
            }
        };
        
        try {
            console.log('📤 Sending message:', { ...payload, message: message.substring(0, 50) + '...' });
            wsRef.current.send(JSON.stringify(payload));
            return true;
        } catch (e) {
            console.error('Failed to send message:', e);
            setError('Failed to send message: ' + e.message);
            setIsStreaming(false);
            return false;
        }
    }, [lastSessionId]);
    
    /**
     * Send a ping to keep connection alive
     */
    const ping = useCallback(() => {
        if (wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send(JSON.stringify({ action: 'ping' }));
        }
    }, []);
    
    /**
     * Set callback for when a complete message is received
     * @param {Function} callback - Called with the complete message object
     */
    const onMessageComplete = useCallback((callback) => {
        messageCallbackRef.current = callback;
    }, []);
    
    /**
     * Set callback for when an error occurs
     * @param {Function} callback - Called with the error message
     */
    const onError = useCallback((callback) => {
        errorCallbackRef.current = callback;
    }, []);
    
    /**
     * Clear the current error
     */
    const clearError = useCallback(() => {
        setError(null);
    }, []);
    
    /**
     * Cancel the current streaming request
     * Note: This closes and reopens the connection
     */
    const cancelStream = useCallback(() => {
        if (isStreaming) {
            disconnect();
            setIsStreaming(false);
            setStreamingText('');
            setStreamingStatus('cancelled');
            
            // Reconnect after a short delay
            setTimeout(() => {
                connect();
            }, 500);
        }
    }, [isStreaming, disconnect, connect]);
    
    // Cleanup on unmount
    useEffect(() => {
        return () => {
            if (reconnectTimeoutRef.current) {
                clearTimeout(reconnectTimeoutRef.current);
            }
            if (wsRef.current) {
                wsRef.current.close(1000, 'Component unmounted');
            }
        };
    }, []);
    
    // Set up heartbeat to keep connection alive (every 5 minutes)
    useEffect(() => {
        if (!isConnected) return;
        
        const heartbeatInterval = setInterval(() => {
            ping();
        }, 5 * 60 * 1000); // 5 minutes
        
        return () => clearInterval(heartbeatInterval);
    }, [isConnected, ping]);
    
    return {
        // Connection state
        isConnected,
        connectionStatus,
        
        // Streaming state
        isStreaming,
        streamingText,
        streamingStatus,
        
        // Data
        sources,
        error,
        lastSessionId,
        
        // Methods
        connect,
        disconnect,
        sendMessage,
        ping,
        cancelStream,
        clearError,
        
        // Callbacks
        onMessageComplete,
        onError
    };
};

export default useWebSocketChat;
