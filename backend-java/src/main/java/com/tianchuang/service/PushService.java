package com.tianchuang.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.config.PushProperties;
import com.tianchuang.entity.AlertEntity;
import com.tianchuang.entity.OutboxEventEntity;
import com.tianchuang.entity.PushLogEntity;
import com.tianchuang.repository.OutboxEventRepo;
import com.tianchuang.repository.PushLogRepo;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class PushService {
    private static final Logger log = LoggerFactory.getLogger(PushService.class);
    private static final int MAX_ATTEMPTS = 3;

    private final PushProperties props;
    private final PushLogRepo pushLogRepo;
    private final OutboxEventRepo outboxRepo;
    private final ObjectMapper mapper;
    private final ObjectProvider<JavaMailSender> mailSenderProvider;
    private final HttpClient http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5)).build();

    public PushService(PushProperties props, PushLogRepo pushLogRepo, OutboxEventRepo outboxRepo,
                       ObjectMapper mapper, ObjectProvider<JavaMailSender> mailSenderProvider) {
        this.props = props;
        this.pushLogRepo = pushLogRepo;
        this.outboxRepo = outboxRepo;
        this.mapper = mapper;
        this.mailSenderProvider = mailSenderProvider;
    }

    @Transactional
    public void enqueueExternal(AlertEntity alert) {
        enqueueOrSkip(alert, "DINGTALK", props.dingtalkWebhook());
        enqueueOrSkip(alert, "FEISHU", props.feishuWebhook());
        enqueueOrSkip(alert, "WECOM", props.wecomWebhook());
        PushProperties.Mail mail = props.mail();
        if (mail != null && mail.enabled() && !blank(mail.to())) enqueue(alert, "MAIL");
        else saveLog(alert.id, "MAIL", "mail", "SKIPPED", 0, "未启用或未配置收件人");
    }

    public void recordScreen(AlertEntity alert, int deliveredSessions) {
        saveLog(alert.id, "SCREEN", "dashboard", deliveredSessions > 0 ? "SENT" : "SKIPPED", 0,
                deliveredSessions > 0 ? "已发送至 " + deliveredSessions + " 个在线客户端" : "当前无在线客户端");
    }

    @Transactional
    public synchronized void recordScreenAck(Long alertId, String sessionId) {
        if (alertId == null || blank(sessionId)) return;
        if (!pushLogRepo.existsByAlertIdAndChannelAndTargetAndStatus(alertId, "SCREEN", sessionId, "DISPLAYED")) {
            saveLog(alertId, "SCREEN", sessionId, "DISPLAYED", 0, "客户端已展示预警");
        }
    }

    private void enqueueOrSkip(AlertEntity alert, String channel, String endpoint) {
        if (blank(endpoint)) saveLog(alert.id, channel, channel.toLowerCase(), "SKIPPED", 0, "未配置");
        else enqueue(alert, channel);
    }

    private void enqueue(AlertEntity alert, String channel) {
        String key = alert.id + ":" + channel;
        if (outboxRepo.existsByEventKey(key)) return;
        OutboxEventEntity event = new OutboxEventEntity();
        event.eventKey = key;
        event.alertId = alert.id;
        event.channel = channel;
        try {
            event.payload = mapper.writeValueAsString(Map.of(
                    "level", alert.level, "region", alert.region, "text", alert.text));
        } catch (Exception e) {
            throw new IllegalStateException("预警 outbox 序列化失败", e);
        }
        outboxRepo.save(event);
        saveLog(alert.id, channel, channel.toLowerCase(), "QUEUED", 0, "等待异步发送");
    }

    @Scheduled(fixedDelayString = "${push.outbox-poll-ms:1000}")
    public void dispatchDue() {
        recoverAbandonedClaims();
        for (OutboxEventEntity event : outboxRepo
                .findTop20ByStatusAndDueAtBeforeOrderByIdAsc("PENDING", LocalDateTime.now().plusNanos(1))) {
            dispatch(event);
        }
    }

    private void dispatch(OutboxEventEntity event) {
        event.status = "SENDING";
        event.attempts += 1;
        event.claimedAt = LocalDateTime.now();
        event.updatedAt = LocalDateTime.now();
        outboxRepo.save(event);
        long started = System.currentTimeMillis();
        try {
            JsonNode payload = mapper.readTree(event.payload);
            switch (event.channel) {
                case "DINGTALK" -> postWebhook(event.channel, props.dingtalkWebhook(), Map.of(
                        "msgtype", "markdown", "markdown", Map.of("title", "低空飞行气象预警",
                                "text", "**【低空飞行气象预警】**\n\n> " + payload.path("text").asText().replace("\n", "\n\n> "))));
                case "FEISHU" -> postWebhook(event.channel, props.feishuWebhook(), Map.of(
                        "msg_type", "text", "content", Map.of("text", payload.path("text").asText())));
                case "WECOM" -> postWebhook(event.channel, props.wecomWebhook(), Map.of(
                        "msgtype", "markdown", "markdown", Map.of("content", payload.path("text").asText())));
                case "MAIL" -> sendMail(payload);
                default -> throw new IllegalStateException("未知推送渠道: " + event.channel);
            }
            event.status = "SENT";
            event.claimedAt = null;
            event.detail = "渠道已受理";
            saveLog(event.alertId, event.channel, event.channel.toLowerCase(), "SENT",
                    (int) (System.currentTimeMillis() - started), event.detail);
        } catch (Exception e) {
            event.detail = safe(e.getMessage());
            if (event.attempts >= MAX_ATTEMPTS) {
                event.status = "DEAD";
                event.claimedAt = null;
                saveLog(event.alertId, event.channel, event.channel.toLowerCase(), "FAILED",
                        (int) (System.currentTimeMillis() - started), event.detail);
            } else {
                event.status = "PENDING";
                event.claimedAt = null;
                event.dueAt = LocalDateTime.now().plusSeconds(1L << event.attempts);
            }
            log.warn("推送失败 channel={} attempt={}: {}", event.channel, event.attempts, event.detail);
        }
        event.updatedAt = LocalDateTime.now();
        outboxRepo.save(event);
    }

    private void recoverAbandonedClaims() {
        LocalDateTime cutoff = LocalDateTime.now().minusMinutes(2);
        for (OutboxEventEntity event : outboxRepo.findByStatusAndClaimedAtBefore("SENDING", cutoff)) {
            event.status = event.attempts >= MAX_ATTEMPTS ? "DEAD" : "PENDING";
            event.dueAt = LocalDateTime.now();
            event.claimedAt = null;
            event.updatedAt = LocalDateTime.now();
            event.detail = "上次投递中断，已自动恢复";
            outboxRepo.save(event);
        }
    }

    private void postWebhook(String channel, String url, Map<String, Object> body) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(10))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body))).build();
        HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() < 200 || response.statusCode() >= 300) {
            throw new IllegalStateException("HTTP " + response.statusCode());
        }
        JsonNode result = mapper.readTree(response.body());
        String codeField = "FEISHU".equals(channel) ? "code" : "errcode";
        if (!result.has(codeField) || result.path(codeField).asInt(Integer.MIN_VALUE) != 0) {
            throw new IllegalStateException("渠道业务响应失败");
        }
    }

    private void sendMail(JsonNode payload) {
        PushProperties.Mail mail = props.mail();
        JavaMailSender sender = mail == null ? null : mailSenderProvider.getIfAvailable();
        if (mail == null || sender == null) throw new IllegalStateException("邮件服务未配置");
        SimpleMailMessage message = new SimpleMailMessage();
        message.setFrom(mail.username());
        message.setTo(mail.to().split(","));
        message.setSubject("【低空飞行气象预警】" + payload.path("level").asText()
                + " · " + payload.path("region").asText());
        message.setText(payload.path("text").asText());
        sender.send(message);
    }

    private void saveLog(Long alertId, String channel, String target, String status,
                         int latency, String detail) {
        PushLogEntity logEntry = new PushLogEntity();
        logEntry.alertId = alertId;
        logEntry.channel = channel;
        logEntry.target = target;
        logEntry.status = status;
        logEntry.latencyMs = latency;
        logEntry.detail = detail;
        pushLogRepo.save(logEntry);
    }

    private boolean blank(String value) { return value == null || value.isBlank(); }
    private String safe(String value) {
        if (value == null) return "未知错误";
        return value.substring(0, Math.min(300, value.length()));
    }
}
