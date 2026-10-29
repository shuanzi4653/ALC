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
import org.springframework.transaction.annotation.Transactional;

@Service
public class AlertService {

    private static final Logger log = LoggerFactory.getLogger(AlertService.class);

    private final QweatherProperties qw;
    private final AlertRepo alertRepo;
    private final PushService pushService;
    private final DashboardWebSocketHandler ws;

    public AlertService(QweatherProperties qw, AlertRepo alertRepo,
                        PushService pushService, DashboardWebSocketHandler ws) {
        this.qw = qw;
        this.alertRepo = alertRepo;
        this.pushService = pushService;
        this.ws = ws;
    }

    @Transactional
    public AlertEntity createAlert(FlightLevel fused, String triggerType,
                                   SfiRecordEntity rec, SfiEngine.SfiResult sfi,
                                   Map<String, Object> track2,
                                   FusionService.FusionResult fr,
                                   FlightLevel t1, FlightLevel t2,
                                   AlertStateService.Decision decision) {
        boolean resolved = decision.action() == AlertStateService.Action.RESOLVE;
        String factors = resolved ? "风险条件已连续两轮解除" : joinFactors(track2, sfi);
        String advice = resolved ? "可按当前最新气象与作业规程重新评估飞行窗口" : switch (fused) {
            case BAN -> "立即停止作业，设备撤收或就近降落";
            case DANGER -> "不建议飞行，已起飞的应立即返航";
            case CAUTION -> "缩短作业窗口并持续监测气象变化";
            case FIT -> "适飞指数出现骤降，请复核趋势后再继续作业";
        };

        AlertEntity a = new AlertEntity();
        a.runId = rec.runId;
        a.episodeId = decision.episodeId();
        a.transitionVersion = decision.transitionVersion();
        a.level = fused.name();
        a.triggerType = triggerType;
        a.region = qw.regionName();
        a.factors = factors;
        a.advice = advice;
        a.status = resolved ? "WITHDRAWN" : "PUBLISHED";
        a.text = resolved ? buildResolvedText(fused, rec, advice)
                : buildText(fused, triggerType, rec, factors, advice);
        a = alertRepo.save(a);

        log.warn("触发预警 [{}] {} {}：{}", triggerType, fused.label, a.region,
                a.text.replace("\n", " | "));

        pushService.enqueueExternal(a);
        int delivered = ws.broadcastAlert(rec.runId, Map.of(
                "id", a.id, "eventId", a.id, "ts", a.ts.toString(), "level", a.level,
                "levelLabel", fused.label, "text", a.text));
        pushService.recordScreen(a, delivered);
        return a;
    }

    private String buildResolvedText(FlightLevel previous, SfiRecordEntity rec, String advice) {
        return "【低空飞行气象预警解除】\n"
                + "时间：" + LocalDateTime.now().toLocalTime().withNano(0) + "\n"
                + "区域：" + qw.regionName() + "\n"
                + "原风险等级：" + previous.label + "\n"
                + "当前 SFI：" + rec.sfi + "\n"
                + "建议措施：" + advice;
    }

    private String buildText(FlightLevel fused, String trigger, SfiRecordEntity rec,
                             String factors, String advice) {
        String head = trigger.equals("SFI_DROP")
                ? "适飞指数骤降（60 分钟内下降至少 30 分，当前 " + rec.sfi + "）"
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
