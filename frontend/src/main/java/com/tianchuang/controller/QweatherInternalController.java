package com.tianchuang.controller;

import com.tianchuang.qweather.QweatherClient;
import java.net.InetAddress;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 内部原始天气接口：只访问和风天气，绝不回调 Python。
 *
 * <p>Python 侧的统一气象快照是唯一归一化入口，本接口只负责“取原始数据 + 标注单位与质量”，
 * 不合并成面向前端的状态，避免两套天气互相矛盾。</p>
 *
 * <p>访问约束：默认仅允许本机回环地址调用；如配置 {@code qweather.internal-token}，
 * 则必须同时携带同名请求头。响应带 60 秒缓存，避免地图拖动或轮询放大和风调用量。</p>
 */
@RestController
@RequestMapping("/api/internal/qweather")
public class QweatherInternalController {

    private static final Logger log = LoggerFactory.getLogger(QweatherInternalController.class);
    private static final long CACHE_MILLIS = 60_000L;

    private final QweatherClient client;
    private final String internalToken;
    private final Map<String, Entry> cache = new ConcurrentHashMap<>();

    private record Entry(Instant at, Map<String, Object> value) {}

    public QweatherInternalController(QweatherClient client,
                                      @Value("${qweather.internal-token:}") String internalToken) {
        this.client = client;
        this.internalToken = internalToken == null ? "" : internalToken;
    }

    @GetMapping("/current")
    public ResponseEntity<Map<String, Object>> current(@RequestParam double lat,
                                                       @RequestParam double lon,
                                                       HttpServletRequest request) {
        return serve("current?"
                + "lat=" + lat + "&lon=" + lon, request,
                () -> client.rawCurrent(lat, lon));
    }

    @GetMapping("/hourly")
    public ResponseEntity<Map<String, Object>> hourly(@RequestParam int hours,
                                                      @RequestParam double lat,
                                                      @RequestParam double lon,
                                                      HttpServletRequest request) {
        return serve("hourly?" + "hours=" + hours + "&lat=" + lat + "&lon=" + lon, request,
                () -> client.rawHourly(hours, lat, lon));
    }

    /** 凭据与调用约束的只读状态，供 Python 侧决定是否启用和风来源。 */
    @GetMapping("/status")
    public ResponseEntity<Map<String, Object>> status(HttpServletRequest request) {
        if (!allowed(request)) return forbidden();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("provider", "QWEATHER");
        body.put("product", "weather/v1");
        body.put("endpoints", java.util.List.of("/api/internal/qweather/current", "/api/internal/qweather/hourly"));
        body.put("cacheSeconds", CACHE_MILLIS / 1000);
        body.put("tokenRequired", !internalToken.isBlank());
        body.put("thunderEstimateMethod", QweatherClient.THUNDER_ESTIMATE_METHOD);
        body.put("note", "凭据是否可用需以最近一次成功调用为准；本接口不返回密钥。");
        return ResponseEntity.ok(body);
    }

    private ResponseEntity<Map<String, Object>> serve(String key, HttpServletRequest request, Call call) {
        if (!allowed(request)) return forbidden();
        Entry hit = cache.get(key);
        Instant now = Instant.now();
        if (hit != null && Duration.between(hit.at(), now).toMillis() < CACHE_MILLIS) {
            return ResponseEntity.ok(withCache(hit.value(), "HIT"));
        }
        try {
            Map<String, Object> value = call.get();
            cache.put(key, new Entry(now, value));
            return ResponseEntity.ok(withCache(value, "MISS"));
        } catch (IllegalArgumentException e) {
            throw e;
        } catch (Exception e) {
            log.warn("内部原始天气调用失败 {}: {}", key, e.getMessage());
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("provider", "QWEATHER");
            body.put("available", false);
            body.put("errorCode", e.getClass().getSimpleName());
            body.put("retryable", true);
            body.put("note", "和风原始接口不可用；调用方应保留上一份快照并标注数据年龄，不得改用随机天气。");
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE).body(body);
        }
    }

    private Map<String, Object> withCache(Map<String, Object> value, String state) {
        Map<String, Object> body = new LinkedHashMap<>(value);
        body.put("available", true);
        body.put("cache", state);
        return body;
    }

    private ResponseEntity<Map<String, Object>> forbidden() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", "INTERNAL_ENDPOINT_RESTRICTED");
        body.put("message", "内部原始天气接口仅允许本机调用或携带已配置的内部令牌");
        body.put("retryable", false);
        return ResponseEntity.status(HttpStatus.FORBIDDEN).body(body);
    }

    private boolean allowed(HttpServletRequest request) {
        if (!internalToken.isBlank() && internalToken.equals(request.getHeader("X-Internal-Token"))) return true;
        String remote = request.getRemoteAddr();
        try {
            InetAddress address = InetAddress.getByName(remote);
            if (address.isLoopbackAddress() || address.isAnyLocalAddress()) return true;
        } catch (Exception e) {
            log.debug("无法解析调用方地址 {}", remote);
        }
        return false;
    }

    @FunctionalInterface
    private interface Call {
        Map<String, Object> get() throws Exception;
    }
}
