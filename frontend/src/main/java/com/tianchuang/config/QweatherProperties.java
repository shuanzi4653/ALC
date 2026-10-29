package com.tianchuang.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/** 和风天气配置（JWT 认证四要素 + 私钥路径 + 默认作业区） */
@ConfigurationProperties(prefix = "qweather")
public record QweatherProperties(
        String apiHost,
        String kid,
        String iss,
        String sub,
        String privateKeyPath,
        double lat,
        double lon,
        String regionName,
        String taskType) {

    public boolean jwtReady() {
        return notBlank(apiHost) && notBlank(kid) && notBlank(iss) && notBlank(sub);
    }

    private static boolean notBlank(String s) {
        return s != null && !s.isBlank();
    }
}
