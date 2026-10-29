package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "push")
public record PushProperties(String dingtalkWebhook, String feishuWebhook, String wecomWebhook,
                             Mail mail) {

    public record Mail(boolean enabled, String host, int port, String username,
                       String password, String to) {
    }
}
