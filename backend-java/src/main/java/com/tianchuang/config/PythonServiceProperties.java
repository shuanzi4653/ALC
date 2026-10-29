package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "python-service")
public record PythonServiceProperties(String baseUrl) {
}
