package com.tianchuang.config;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.ViewControllerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;
import org.springframework.beans.factory.annotation.Value;

@Configuration
public class WebConfig implements WebMvcConfigurer {
    private final String externalPath;

    public WebConfig(@Value("${frontend.external-path:}") String externalPath) {
        this.externalPath = externalPath == null ? "" : externalPath.trim();
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        var handler = registry.addResourceHandler("/**");
        if (!externalPath.isBlank()) {
            String normalized = externalPath.replace('\\', '/');
            if (!normalized.endsWith("/")) normalized += "/";
            handler.addResourceLocations("file:" + normalized);
        }
        handler.addResourceLocations("classpath:/static/");
    }

    @Override
    public void addViewControllers(ViewControllerRegistry registry) {
        registry.addViewController("/").setViewName("forward:/index.html");
    }
}
