package com.tianchuang.service;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.tianchuang.config.QweatherProperties;
import com.tianchuang.entity.AlertEntity;
import com.tianchuang.entity.SfiRecordEntity;
import com.tianchuang.model.FlightLevel;
import com.tianchuang.model.WeatherSnapshot;
import com.tianchuang.repository.AlertRepo;
import com.tianchuang.ws.DashboardWebSocketHandler;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 预警服务：生成预警文本（模板）+ 多渠道推送（对应计划书 6.1/6.2 节）
 * 初代版本发布文本以规则模板为准，LLM 润色文本作为补充展示（轨2 alert_text）。
 */
@Service
public class AlertService {

    private static final Logger log = LoggerFactory.getLogger(AlertService.class);

    private final QweatherProperties qw;
    private final AlertRepo alertRepo;
    private final PushService pushService;
    private final DashboardWebSocketHandler ws;
    private final ObjectMapper mapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);

    public AlertService(QweatherProperties qw, AlertRepo alertRepo,
                        PushService pushService, DashboardWebSocketHandler ws) {
        this.qw = qw;
        this.alertRepo = alertRepo;
        this.pushService = pushService;
        this.ws = ws;
    }

    public AlertEntity createAlert(FlightLevel fused, String triggerType,
                                   SfiRecordEntity rec, SfiEngine.SfiResult sfi,
                                   Map<String, Object> track2,
                                   FusionService.FusionResult fr,
                                   FlightLevel t1, FlightLevel t2) {
        String factors = joinFactors(track2, sfi);
        String advice = String.valueOf(track2.get("advice"));
        if (advice == null || advice.isBlank() || "null".equals(advice)) {
            advice = fused == FlightLevel.BAN ? "立即停止作业，设备撤收或就近降落"
                    : "不建议飞行，已起飞的应立即返航";
        }

        AlertEntity a = new AlertEntity();
        a.level = fused.name();
        a.triggerType = triggerType;
        a.region = qw.regionName();
        a.factors = factors;
        a.advice = advice;
        a.status = "PUBLISHED";
        a.text = buildText(fused, triggerType, rec, factors, advice);
        a = alertRepo.save(a);

        log.warn("触发预警 [{}] {} {}：{}", triggerType, fused.label, a.region,
                a.text.replace("\n", " | "));

        // 多渠道推送 + 大屏弹窗广播
        pushService.pushAll(a);
        try {
            ws.broadcast(mapper.writeValueAsString(Map.of(
                    "type", "alert", "alert", Map.of(
                            "id", a.id, "ts", a.ts.toString(), "level", a.level,
                            "levelLabel", fused.label, "text", a.text))));
        } catch (Exception e) {
            log.warn("预警弹窗广播失败: {}", e.getMessage());
        }
        return a;
    }

    private String buildText(FlightLevel fused, String trigger, SfiRecordEntity rec,
                             String factors, String advice) {
        String head = trigger.equals("SFI_DROP")
                ? "适飞指数骤降（60 分钟内下降超 30 分，当前 " + rec.sfi + "）"
                : "综合研判风险等级达「" + fused.label + "」（SFI " + rec.sfi + "）";
        return "【低空飞行气象预警】\n"
                + "时间：" + LocalDateTime.now().toLocalTime().withNano(0) + "\n"
                + "区域：" + qw.regionName() + "\n"
                + "触发原因：" + head + "\n"
                + "影响要素：" + factors + "\n"
                + "建议措施：" + advice;
    }

    private String joinFactors(Map<String, Object> track2, SfiEngine.SfiResult sfi) {
        Object kf = track2.get("key_factors");
        if (kf instanceof List<?> list && !list.isEmpty()) {
            return String.join("；", list.stream().map(String::valueOf).limit(4).toList());
        }
        StringBuilder sb = new StringBuilder();
        for (SfiEngine.Check c : sfi.checks()) {
            if (c.banned() || c.warn()) {
                if (!sb.isEmpty()) sb.append("；");
                sb.append(c.factor()).append(" ").append(c.value()).append(c.unit());
            }
        }
        return sb.isEmpty() ? "无明显异常要素" : sb.toString();
    }
}
