package com.tianchuang.qweather;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.config.QweatherProperties;
import com.tianchuang.model.ForecastHour;
import com.tianchuang.model.WeatherSnapshot;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 和风天气 v1 API 客户端
 *   GET /weather/v1/current/{lat}/{lon}      实时天气
 *   GET /weather/v1/hourly/{lat}/{lon}?hours=N  逐小时预报
 * 认证：Authorization: Bearer <JWT>
 */
@Service
public class QweatherClient {

    private static final Logger log = LoggerFactory.getLogger(QweatherClient.class);

    private final QweatherProperties props;
    private final QweatherJwtService jwtService;
    private final ObjectMapper mapper = new ObjectMapper();
    private final HttpClient http = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(10))
            .followRedirects(HttpClient.Redirect.NORMAL)
            .build();

    public QweatherClient(QweatherProperties props, QweatherJwtService jwtService) {
        this.props = props;
        this.jwtService = jwtService;
    }

    /** 拉取实时观测并标准化 */
    public WeatherSnapshot current() throws Exception {
        String url = "https://" + props.apiHost() + "/weather/v1/current/"
                + props.lat() + "/" + props.lon() + "?localTime=true&lang=zh";
        JsonNode root = getJson(url);
        JsonNode c = root.path("condition");
        JsonNode wind = root.path("wind").path("speed");
        JsonNode gust = root.path("windGust");
        JsonNode precip = root.path("precipitation").path("intensity");
        JsonNode vis = root.path("visibility");
        String time = root.path("metadata").path("obsTime").asText(null);
        if (time == null || time.isBlank()) {
            time = java.time.OffsetDateTime.now().toString();
        }
        double thunder = estimateThunder(c.path("code").asText("100"), root.path("cloudCover").asDouble(0));
        return new WeatherSnapshot(
                time, "live", props.lat(), props.lon(),
                c.path("text").asText("未知"),
                root.path("temperature").path("value").asDouble(0),
                root.path("humidity").asDouble(0),
                wind.path("value").asDouble(0),
                gust.path("value").asDouble(0),
                root.path("wind").path("direction").path("degree").asInt(0),
                precip.path("value").asDouble(0),
                vis.path("value").asDouble(20000),
                root.path("pressure").path("value").asDouble(1010),
                root.path("cloudCover").asDouble(0),
                thunder);
    }

    /** 拉取逐小时预报并标准化 */
    public List<ForecastHour> hourly(int hours) throws Exception {
        String url = "https://" + props.apiHost() + "/weather/v1/hourly/"
                + props.lat() + "/" + props.lon() + "?hours=" + hours + "&localTime=true&lang=zh";
        JsonNode root = getJson(url);
        List<ForecastHour> list = new ArrayList<>();
        for (JsonNode h : root.path("hours")) {
            list.add(new ForecastHour(
                    h.path("forecastTime").asText(""),
                    h.path("temperature").path("value").asDouble(0),
                    h.path("wind").path("speed").path("value").asDouble(0),
                    h.path("windGust").path("value").asDouble(0),
                    h.path("precipitation").path("intensity").path("value").asDouble(0),
                    h.path("visibility").path("value").asDouble(20000),
                    thunderFromPrecipProb(h.path("precipitation").path("probability").asDouble(0))));
        }
        return list;
    }

    /** 用云量+降水概率粗估雷暴概率（v1 API 无独立雷暴字段时的工程近似，方案中已说明） */
    private double estimateThunder(String conditionCode, double cloudCover) {
        // 30x 段天气代码：30 开头为雷雨/降水类现象
        if (conditionCode.startsWith("302") || conditionCode.startsWith("304")) return 0.85;
        if (conditionCode.startsWith("30")) return 0.35;
        return Math.max(0, Math.min(0.2, (cloudCover - 0.7) * 0.5));
    }

    private double thunderFromPrecipProb(double prob) {
        return Math.max(0, Math.min(0.9, prob * 0.6));
    }

    private JsonNode getJson(String url) throws Exception {
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(20))
                .header("Authorization", "Bearer " + jwtService.bearerToken())
                .GET()
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            log.warn("和风 API 响应 {} {}: {}", resp.statusCode(), url, abbreviate(resp.body()));
            throw new IllegalStateException("和风 API HTTP " + resp.statusCode());
        }
        return mapper.readTree(resp.body());
    }

    private String abbreviate(String s) {
        return s == null ? "" : s.substring(0, Math.min(200, s.length()));
    }
}
