package com.tianchuang.service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.List;
import java.util.Map;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.config.PythonServiceProperties;
import com.tianchuang.config.QweatherProperties;
import com.tianchuang.model.ForecastHour;
import com.tianchuang.model.WeatherSnapshot;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * Python 智能服务客户端（8600）：模拟数据生成器 + 轨2 研判 + 智能体问答
 */
@Service
public class PythonClient {

    private static final Logger log = LoggerFactory.getLogger(PythonClient.class);

    private final PythonServiceProperties pyProps;
    private final QweatherProperties qwProps;
    private final ObjectMapper mapper = new ObjectMapper();
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    public PythonClient(PythonServiceProperties pyProps, QweatherProperties qwProps) {
        this.pyProps = pyProps;
        this.qwProps = qwProps;
    }

    /**
     * 所有出站请求的**唯一**构造出口：工作区头只在这里加。
     *
     * <p>Python 侧的工作区靠请求头识别（见 {@code workspace.py}）。如果每个方法各自加头，
     * 迟早有一个方法忘掉 —— 而忘掉的那条链路会安静地按"未标识"读写全局数据：症状是
     * "某个面板两个人看到同一份"，而所有判据依旧全绿。收成一个方法，只可能全对或全错。</p>
     *
     * <p>空工作区<b>不发这个头</b>，而不是发一个空值：Python 侧把"头不存在"与"头是空串"
     * 都归一成未标识，但少发一个头让抓包和 access log 里两种情况的区别是可见的。</p>
     */
    private HttpRequest.Builder builder(String path) {
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(pyProps.baseUrl() + path))
                .header("Content-Type", "application/json");
        String workspace = com.tianchuang.config.WorkspaceContext.current();
        if (workspace != null && !workspace.isBlank()) {
            builder.header(com.tianchuang.config.WorkspaceContext.HEADER, workspace);
        }
        // 0.11.6（E-3）：操作身份，同样只在这一个出口加。
        // 不带就**不发这个头** —— 让"未提供"在抓包里可见，而不是发一个空串。
        String operator = com.tianchuang.config.OperatorContext.current();
        if (operator != null && !operator.isBlank()) {
            builder.header(com.tianchuang.config.OperatorContext.HEADER, operator);
        }
        return builder;
    }

    /**
     * 读取真实气象快照，返回 {snapshot, hourly, provider} 原始 JSON。
     *
     * 取代了原来的 /sim/generate（合成剧本）。出口结构逐字段一致，因此
     * WeatherSnapshot / ForecastHour 的反序列化无需改动；变化在语义——取不到
     * 数据时本方法抛异常，调用方必须显式降级，不再有编造的兜底值。
     */
    @SuppressWarnings("unchecked")
    public Map<String, Object> currentWeather(int hours) throws Exception {
        String url = "/weather/current?hours=" + hours
                + "&lat=" + qwProps.lat() + "&lon=" + qwProps.lon();
        HttpRequest req = builder(url).timeout(Duration.ofSeconds(15)).GET().build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("真实气象服务 HTTP " + resp.statusCode() + ": " + abbreviate(resp.body()));
        }
        return mapper.readValue(resp.body(), Map.class);
    }

    /** 轨2 大模型研判 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> track2(String runId, long deadlineEpochMs, WeatherSnapshot snap,
                                      List<ForecastHour> forecast, String region, String taskType) throws Exception {
        Map<String, Object> body = Map.of(
                "run_id", runId,
                "deadline_epoch_ms", deadlineEpochMs,
                "snapshot", mapper.convertValue(snap, Map.class),
                "forecast", forecast.stream().map(f -> mapper.convertValue(f, Map.class)).toList(),
                "region", region,
                "task_type", taskType);
        HttpRequest req = builder("/track2")
                .timeout(Duration.ofSeconds(22))
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)))
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("轨2 服务 HTTP " + resp.statusCode() + ": " + abbreviate(resp.body()));
        }
        return mapper.readValue(resp.body(), Map.class);
    }

    /** 智能体问答 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> ask(String question, String context) throws Exception {
        Map<String, Object> body = Map.of("question", question, "context", context);
        HttpRequest req = builder("/agent/ask")
                .timeout(Duration.ofSeconds(60))
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)))
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("问答服务 HTTP " + resp.statusCode());
        }
        return mapper.readValue(resp.body(), Map.class);
    }

    /**
     * 原样转发（0.11.6 / E-2）。
     *
     * `decisionRequest` 会把响应体 `mapper.readValue(..., Object.class)` —— 那假设
     * 响应是 JSON。而 `/traffic/metrics` 是 **Prometheus 文本格式**，于是
     * `trafficMetrics` 在 Java 侧抛解析异常，接口直接 500。
     * 这里不做任何解析：body 与 Content-Type 原样透传，状态码也透传。
     */
    public org.springframework.http.ResponseEntity<String> rawGet(String path) throws Exception {
        HttpRequest req = builder(path).timeout(Duration.ofSeconds(15)).GET().build();
        java.net.http.HttpResponse<String> resp = http.send(req, java.net.http.HttpResponse.BodyHandlers.ofString());
        String contentType = resp.headers().firstValue("content-type").orElse("text/plain; charset=utf-8");
        return org.springframework.http.ResponseEntity.status(resp.statusCode())
                .header("Content-Type", contentType)
                .header("Cache-Control", "no-store")
                .body(resp.body());
    }

    public org.springframework.http.ResponseEntity<?> decisionRequest(String path, Map<String, Object> body) throws Exception {
        HttpRequest.Builder requestBuilder = builder(path).timeout(Duration.ofSeconds(30));
        if (body == null) requestBuilder.GET();
        else requestBuilder.POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)));
        HttpResponse<String> response = http.send(requestBuilder.build(), HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() >= 400) {
            String message = "决策请求被拒绝，请检查输入、时次或记录是否存在";
            // 0.11.5（W-31）：422 必须透出**缺的是哪个参数**。
            // 原来一律用上面那句通用消息，于是 `/traffic/operations` 少了必填的
            // `sessionId` 时，界面上写的是"请检查输入、时次或记录是否存在" ——
            // 复测报告据此判断成"case 参数没落地"，其实是**缺一个必填 query**。
            // 一句含糊的错误消息，会让人去查一个不存在的 bug。
            // 局部名不能叫 `body`：方法参数已经是 `Map<String,Object> body`
            var errorBody = mapper.readTree(response.body());
            var detail = errorBody.path("detail");
            if (detail.isTextual() && detail.asText().length() <= 160) {
                message = detail.asText();
            } else if (detail.isArray() && detail.size() > 0) {
                // FastAPI 的 422 形状：[{loc:["query","sessionId"], msg:"Field required", ...}]
                var first = detail.get(0);
                StringBuilder where = new StringBuilder();
                var loc = first.path("loc");
                if (loc.isArray()) {
                    for (var node : loc) {
                        if (where.length() > 0) where.append('.');
                        where.append(node.asText());
                    }
                }
                String why = first.path("msg").asText("");
                if (!why.isEmpty()) message = (where.isEmpty() ? "" : where + "：") + why;
            }
            return org.springframework.http.ResponseEntity.status(response.statusCode()).body(
                    Map.of("code", "DECISION_REQUEST_FAILED", "message", message, "retryable", false));
        }
        // 0.11.6（E-1⑤）：透传上游的 ETag 与 Cache-Control。
        // 不透传的话，Python 侧预序列化时算出的 ETag 到不了浏览器，
        // `If-None-Match` -> 304 这条链路整条作废（省下的只是服务端 CPU，不是传输）。
        var ok = org.springframework.http.ResponseEntity.ok();
        var etag = response.headers().firstValue("etag");
        var cacheControl = response.headers().firstValue("cache-control");
        etag.ifPresent(value -> ok.header("ETag", value));
        cacheControl.ifPresent(value -> ok.header("Cache-Control", value));
        return ok.body(mapper.readValue(response.body(), Object.class));
    }

    public java.util.List<com.tianchuang.dto.LayerDto> weatherLayers(Map<String, Object> dashboard) throws Exception {
        HttpRequest request = builder("/weather/layers")
                .timeout(Duration.ofSeconds(8))
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(dashboard))).build();
        HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200) throw new IllegalStateException("天气计算服务不可用");
        return mapper.readValue(response.body(), mapper.getTypeFactory().constructCollectionType(
                java.util.List.class, com.tianchuang.dto.LayerDto.class));
    }

    private String abbreviate(String s) {
        return s == null ? "" : s.substring(0, Math.min(200, s.length()));
    }
}
