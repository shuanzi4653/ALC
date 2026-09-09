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

    /** 调用模拟数据生成器，返回 {scenario, snapshot, hourly} 原始 JSON */
    @SuppressWarnings("unchecked")
    public Map<String, Object> generateSim(String scenario, int hours) throws Exception {
        String url = pyProps.baseUrl() + "/sim/generate?scenario=" + scenario
                + "&hours=" + hours + "&lat=" + qwProps.lat() + "&lon=" + qwProps.lon();
        HttpRequest req = HttpRequest.newBuilder(URI.create(url)).timeout(Duration.ofSeconds(15)).GET().build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("模拟生成器 HTTP " + resp.statusCode() + ": " + abbreviate(resp.body()));
        }
        return mapper.readValue(resp.body(), Map.class);
    }

    /** 轨2 大模型研判 */
    @SuppressWarnings("unchecked")
    public Map<String, Object> track2(WeatherSnapshot snap, List<ForecastHour> forecast,
                                      String region, String taskType) throws Exception {
        Map<String, Object> body = Map.of(
                "snapshot", mapper.convertValue(snap, Map.class),
                "forecast", forecast.stream().map(f -> mapper.convertValue(f, Map.class)).toList(),
                "region", region,
                "task_type", taskType);
        HttpRequest req = HttpRequest.newBuilder(URI.create(pyProps.baseUrl() + "/track2"))
                .timeout(Duration.ofSeconds(90))
                .header("Content-Type", "application/json")
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
        HttpRequest req = HttpRequest.newBuilder(URI.create(pyProps.baseUrl() + "/agent/ask"))
                .timeout(Duration.ofSeconds(60))
                .header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body)))
                .build();
        HttpResponse<String> resp = http.send(req, HttpResponse.BodyHandlers.ofString());
        if (resp.statusCode() != 200) {
            throw new IllegalStateException("问答服务 HTTP " + resp.statusCode());
        }
        return mapper.readValue(resp.body(), Map.class);
    }

    private String abbreviate(String s) {
        return s == null ? "" : s.substring(0, Math.min(200, s.length()));
    }
}
