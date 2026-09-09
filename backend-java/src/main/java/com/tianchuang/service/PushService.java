package com.tianchuang.service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.config.PushProperties;
import com.tianchuang.entity.AlertEntity;
import com.tianchuang.entity.PushLogEntity;
import com.tianchuang.repository.PushLogRepo;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.mail.SimpleMailMessage;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.stereotype.Service;

/**
 * 预警多渠道推送（对应计划书第六章推送矩阵）
 * 必做渠道：SCREEN（大屏 WebSocket 弹窗，恒成功）
 * 可配置渠道：钉钉/飞书/企业微信 Webhook、邮件 SMTP
 */
@Service
public class PushService {

    private static final Logger log = LoggerFactory.getLogger(PushService.class);

    private final PushProperties props;
    private final PushLogRepo pushLogRepo;
    private final ObjectMapper mapper = new ObjectMapper();
    /** 按需注入：邮件未配置（无 spring.mail 自动装配）时为 null，不影响其他渠道 */
    private final ObjectProvider<JavaMailSender> mailSenderProvider;
    private final HttpClient http = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5)).build();

    public PushService(PushProperties props, PushLogRepo pushLogRepo,
                       ObjectProvider<JavaMailSender> mailSenderProvider) {
        this.props = props;
        this.pushLogRepo = pushLogRepo;
        this.mailSenderProvider = mailSenderProvider;
    }

    /** 将预警推送至全部渠道，逐渠道记录 PushLog */
    public void pushAll(AlertEntity alert) {
        // SCREEN：大屏弹窗（WebSocket 由调用方广播，此处记录渠道成功）
        saveLog(alert.id, "SCREEN", "dashboard", "SENT", 0, "大屏弹窗已广播");

        // 钉钉群机器人
        if (blank(props.dingtalkWebhook())) {
            saveLog(alert.id, "DINGTALK", "-", "SKIPPED", 0, "未配置");
        } else {
            Map<String, Object> body = Map.of("msgtype", "markdown",
                    "markdown", Map.of("title", "低空飞行气象预警",
                            "text", "**【低空飞行气象预警】**\n\n> " + alert.text.replace("\n", "\n\n> ")));
            postWebhook("DINGTALK", props.dingtalkWebhook(), alert, body);
        }

        // 飞书群机器人
        if (blank(props.feishuWebhook())) {
            saveLog(alert.id, "FEISHU", "-", "SKIPPED", 0, "未配置");
        } else {
            Map<String, Object> body = Map.of("msg_type", "text",
                    "content", Map.of("text", "【低空飞行气象预警】\n" + alert.text));
            postWebhook("FEISHU", props.feishuWebhook(), alert, body);
        }

        // 企业微信群机器人
        if (blank(props.wecomWebhook())) {
            saveLog(alert.id, "WECOM", "-", "SKIPPED", 0, "未配置");
        } else {
            Map<String, Object> body = Map.of("msgtype", "markdown",
                    "markdown", Map.of("content", "【低空飞行气象预警】\n" + alert.text));
            postWebhook("WECOM", props.wecomWebhook(), alert, body);
        }

        // 邮件
        PushProperties.Mail mail = props.mail();
        JavaMailSender mailSender = mail != null && mail.enabled()
                ? mailSenderProvider.getIfAvailable() : null;
        if (mail == null || !mail.enabled() || blank(mail.to()) || mailSender == null) {
            saveLog(alert.id, "MAIL", "-", "SKIPPED", 0, "未启用");
        } else {
            long t0 = System.currentTimeMillis();
            try {
                SimpleMailMessage msg = new SimpleMailMessage();
                msg.setFrom(mail.username());
                msg.setTo(mail.to().split(","));
                msg.setSubject("【低空飞行气象预警】" + alert.level + " · " + alert.region);
                msg.setText(alert.text);
                mailSender.send(msg);
                saveLog(alert.id, "MAIL", mail.to(), "SENT",
                        (int) (System.currentTimeMillis() - t0), null);
            } catch (Exception e) {
                saveLog(alert.id, "MAIL", mail.to(), "FAILED",
                        (int) (System.currentTimeMillis() - t0), e.getMessage());
            }
        }
    }

    private void postWebhook(String channel, String url, AlertEntity alert, Map<String, Object> body) {
        long t0 = System.currentTimeMillis();
        try {
            HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                    .timeout(Duration.ofSeconds(10))
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)))
                    .build();
            HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
            saveLog(alert.id, channel, abbreviate(url),
                    resp.statusCode() == 200 ? "SENT" : "FAILED",
                    (int) (System.currentTimeMillis() - t0),
                    resp.statusCode() == 200 ? null : "HTTP " + resp.statusCode());
        } catch (Exception e) {
            saveLog(alert.id, channel, abbreviate(url), "FAILED",
                    (int) (System.currentTimeMillis() - t0), e.getMessage());
        }
    }

    private void saveLog(Long alertId, String channel, String target, String status, int latency, String detail) {
        PushLogEntity l = new PushLogEntity();
        l.alertId = alertId;
        l.channel = channel;
        l.target = target;
        l.status = status;
        l.latencyMs = latency;
        l.detail = detail;
        pushLogRepo.save(l);
        if ("FAILED".equals(status)) {
            log.warn("推送失败 {} {}: {}", channel, target, detail);
        }
    }

    private boolean blank(String s) {
        return s == null || s.isBlank();
    }

    private String abbreviate(String s) {
        return s.length() > 40 ? s.substring(0, 40) + "..." : s;
    }
}
