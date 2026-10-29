package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** Python 智能服务连接配置 */
@ConfigurationProperties(prefix = "python-service")
public record PythonServiceProperties(String baseUrl) {
}
