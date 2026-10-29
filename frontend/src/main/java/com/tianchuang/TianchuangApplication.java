package com.tianchuang;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 天窗智巡：低空飞行气象保障系统 · 主服务
 * 端口 8085；Python 智能服务端口 8600；H2 嵌入式数据库
 */
@SpringBootApplication
@EnableScheduling
@ConfigurationPropertiesScan
public class TianchuangApplication {

    public static void main(String[] args) {
        SpringApplication.run(TianchuangApplication.class, args);
    }
}
