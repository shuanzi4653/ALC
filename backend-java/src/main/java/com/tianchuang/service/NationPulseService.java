package com.tianchuang.service;

import java.util.LinkedHashMap;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.ws.DashboardWebSocketHandler;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * 全国层状态心跳。
 *
 * 为什么不让前端自己轮询：全国页空闲时也要知道"雷达换帧了没有、实况更新了没有"，
 * 每 5 秒拉一次 500 KB 的整份数据是浪费；这里只拉一条几十字节的心跳，
 * 判定有变化才广播 `changed=true`，前端收到再按需拉取。
 *
 * 变化判据是三件事：雷达帧时间、实况取数时间、模型版本。
 * 这三件任一变化，图上的绕飞、低能见度、概率就会变，必须重取。
 */
@Service
public class NationPulseService {

    private static final Logger log = LoggerFactory.getLogger(NationPulseService.class);

    private final PythonClient python;
    private final DashboardWebSocketHandler ws;
    private final ObjectMapper mapper;
    private String lastKey = "";

    public NationPulseService(PythonClient python, DashboardWebSocketHandler ws, ObjectMapper mapper) {
        this.python = python;
        this.ws = ws;
        this.mapper = mapper;
    }

    @Scheduled(initialDelayString = "${nation.pulse-initial-delay-ms:9000}",
               fixedDelayString = "${nation.pulse-ms:5000}")
    public void tick() {
        try {
            var response = python.rawGet("/traffic/v2/nation/pulse");
            String body = response.getBody();
            if (!response.getStatusCode().is2xxSuccessful() || body == null || body.isBlank()) {
                return;
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> pulse = mapper.readValue(body, Map.class);
            String key = String.valueOf(pulse.get("radarTs")) + "|" + pulse.get("weatherAt")
                    + "|" + pulse.get("modelVersion") + "|" + pulse.get("radarBands");
            boolean changed = !key.equals(lastKey);
            lastKey = key;
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("pulse", pulse);
            payload.put("changed", changed);
            ws.broadcast("nation_pulse", payload);
        } catch (Exception e) {
            // Python 不在线时这条会每 5 秒失败一次：只记 debug，不刷 warn
            log.debug("全国心跳拉取失败: {}", e.getMessage());
        }
    }
}
