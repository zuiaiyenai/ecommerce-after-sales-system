package com.ecommerce.aftersales.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.io.IOException;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArraySet;

@Slf4j
@Component
public class ChatWebSocketHandler extends TextWebSocketHandler {

    private static final Map<Long, Set<WebSocketSession>> SUBSCRIPTIONS = new ConcurrentHashMap<>();
    private static final Map<String, Long> SESSION_SUBSCRIBED = new ConcurrentHashMap<>();

    private final ObjectMapper objectMapper;

    public ChatWebSocketHandler(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        log.info("WebSocket connected: {}", session.getId());
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) throws Exception {
        String payload = message.getPayload();
        try {
            Map<String, Object> msg = objectMapper.readValue(payload, Map.class);
            String action = (String) msg.get("action");
            Object sessionIdObj = msg.get("sessionId");

            if ("subscribe".equals(action) && sessionIdObj != null) {
                Long sessionId = Long.valueOf(sessionIdObj.toString());
                subscribe(session, sessionId);
                log.info("WebSocket session {} subscribed to chat session {}", session.getId(), sessionId);
            } else if ("unsubscribe".equals(action) && sessionIdObj != null) {
                Long sessionId = Long.valueOf(sessionIdObj.toString());
                unsubscribe(session, sessionId);
            }
        } catch (Exception e) {
            log.warn("Failed to parse WebSocket message: {}", payload, e);
        }
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        Long subscribedId = SESSION_SUBSCRIBED.remove(session.getId());
        if (subscribedId != null) {
            Set<WebSocketSession> sessions = SUBSCRIPTIONS.get(subscribedId);
            if (sessions != null) {
                sessions.remove(session);
                if (sessions.isEmpty()) {
                    SUBSCRIPTIONS.remove(subscribedId);
                }
            }
        }
        log.info("WebSocket disconnected: {}", session.getId());
    }

    private void subscribe(WebSocketSession session, Long chatSessionId) {
        // Unsubscribe from previous
        Long prev = SESSION_SUBSCRIBED.remove(session.getId());
        if (prev != null) {
            Set<WebSocketSession> prevSet = SUBSCRIPTIONS.get(prev);
            if (prevSet != null) {
                prevSet.remove(session);
                if (prevSet.isEmpty()) {
                    SUBSCRIPTIONS.remove(prev);
                }
            }
        }
        // Subscribe to new
        SUBSCRIPTIONS.computeIfAbsent(chatSessionId, k -> new CopyOnWriteArraySet<>()).add(session);
        SESSION_SUBSCRIBED.put(session.getId(), chatSessionId);
    }

    private void unsubscribe(WebSocketSession session, Long chatSessionId) {
        Set<WebSocketSession> sessions = SUBSCRIPTIONS.get(chatSessionId);
        if (sessions != null) {
            sessions.remove(session);
            if (sessions.isEmpty()) {
                SUBSCRIPTIONS.remove(chatSessionId);
            }
        }
        SESSION_SUBSCRIBED.remove(session.getId());
    }

    public void broadcastToSession(Long chatSessionId, Object message) {
        Set<WebSocketSession> sessions = SUBSCRIPTIONS.get(chatSessionId);
        if (sessions == null || sessions.isEmpty()) {
            return;
        }
        try {
            String json = objectMapper.writeValueAsString(message);
            TextMessage textMessage = new TextMessage(json);
            for (WebSocketSession ws : sessions) {
                if (ws.isOpen()) {
                    try {
                        ws.sendMessage(textMessage);
                    } catch (IOException e) {
                        log.warn("Failed to send WebSocket message to session {}", ws.getId());
                    }
                }
            }
        } catch (Exception e) {
            log.error("Failed to serialize WebSocket message", e);
        }
    }
}
