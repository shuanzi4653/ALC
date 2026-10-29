package com.tianchuang.config;

import java.io.File;
import java.io.InputStream;
import java.util.List;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.model.RuleSpec;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Component;

/**
 * 版本化规则配置加载（可审计）。
 * 优先级：外部 config/rules-v1.json → classpath rules-v1.json → 内置默认（等价 v1 阈值）。
 * 阈值、比较方向、扣分与等级边界全部来自配置，代码不再硬编码数值。
 */
@Component
public class RuleProperties {

    private static final Logger log = LoggerFactory.getLogger(RuleProperties.class);
    private static final ObjectMapper MAPPER = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    private final RuleSpec spec;
    private final String source;

    @Autowired
    public RuleProperties(@Value("${rules.config-file:./config/rules-v1.json}") String externalPath,
                          @Value("${rules.version:v1}") String fallbackVersion,
                          @Value("${rules.hard-ban-enabled:true}") boolean fallbackHardBan) {
        RuleSpec loaded = null;
        String from = "built-in-defaults";

        File external = new File(externalPath);
        if (external.isFile()) {
            loaded = tryRead(external);
            if (loaded != null) {
                from = external.getAbsolutePath();
            } else {
                log.warn("规则文件解析失败，继续尝试 classpath 兜底：{}", externalPath);
            }
        }

        if (loaded == null) {
            try (InputStream in = new ClassPathResource("rules-v1.json").getInputStream()) {
                loaded = MAPPER.readValue(in, RuleSpec.class);
                from = "classpath:rules-v1.json";
            } catch (Exception e) {
                log.warn("未找到可用规则配置，使用内置默认规则（等价 v1 阈值）：{}", e.getMessage());
            }
        }

        this.spec = loaded != null ? loaded : RuleSpec.defaults(fallbackVersion, fallbackHardBan);
        this.source = from;
        log.info("规则配置已加载：version={} source={} factors={} hardBan={}",
                spec.version(), source, spec.factors().size(), spec.hardBanEnabled());
    }

    /** 兼容手工构造（单元测试使用内置默认阈值）。 */
    public RuleProperties(String version, boolean hardBanEnabled) {
        this.spec = RuleSpec.defaults(version, hardBanEnabled);
        this.source = "test-defaults";
    }

    private RuleSpec tryRead(File f) {
        try {
            return MAPPER.readValue(f, RuleSpec.class);
        } catch (Exception e) {
            log.warn("解析规则文件失败 {}：{}", f.getPath(), e.getMessage());
            return null;
        }
    }

    public String version() {
        return spec.version();
    }

    public boolean hardBanEnabled() {
        return spec.hardBanEnabled();
    }

    /** 硬约束命中时对外 SFI 的上限（默认 39，来自配置）。 */
    public int hardBanSfiCap() {
        return spec.hardBanSfiCap();
    }

    public RuleSpec.LevelBounds levels() {
        return spec.levels();
    }

    public List<RuleSpec.FactorRule> factors() {
        return spec.factors();
    }

    public RuleSpec spec() {
        return spec;
    }

    /** 配置来源（外部路径 / classpath / 内置默认），供健康与审计展示。 */
    public String source() {
        return source;
    }
}
