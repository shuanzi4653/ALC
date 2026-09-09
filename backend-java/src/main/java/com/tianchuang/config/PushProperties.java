package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** 预警推送渠道配置 */
@ConfigurationProperties(prefix = "push")
public record PushProperties(String dingtalkWebhook, String feishuWebhook, String wecomWebhook,
                             Mail mail) {

    /** 收件邮箱，多个用逗号分隔（与 application.yml 中 push.mail.to 语义一致） */
    public record Mail(boolean enabled, String host, int port, String username,
                       String password, String to) {
    }
}
