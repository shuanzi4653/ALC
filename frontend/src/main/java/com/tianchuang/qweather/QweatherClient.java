package com.tianchuang.qweather;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.zip.GZIPInputStream;

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
 *   GET /weather/v1/current/{lat}/{lon}         实时天气
 *   GET /weather/v1/hourly/{lat}/{lon}?hours=N  逐小时预报
 * 认证：Authorization: Bearer &lt;JWT&gt;
 *
 * 坐标即可显式传入，回退到配置的默认作业区。原始响应与标准单位一并返回，
 * 由调用方决定质量状态；本类不做“看起来像真的”字段填充。
 */
@Service
public class QweatherClient {

    private static final Logger log = LoggerFactory.getLogger(QweatherClient.class);

    /** 雷暴估算方法标识：不是观测，也不是预报产品字段。 */
    public static final String THUNDER_ESTIMATE_METHOD = "CONDITION_CODE_AND_CLOUD_COVER_HEURISTIC";

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

    /** 拉取默认作业区实时观测并标准化 */
    public WeatherSnapshot current() throws Exception {
        return current(props.lat(), props.lon());
    }

    /** 拉取指定坐标实时观测并标准化 */
    public WeatherSnapshot current(double lat, double lon) throws Exception {
        checkCoordinate(lat, lon);
        JsonNode root = getJson(currentUrl(lat, lon));
        JsonNode c = root.path("condition");
        JsonNode wind = root.path("wind").path("speed");
        JsonNode gust = root.path("windGust");
        JsonNode precip = root.path("precipitation").path("intensity");
        JsonNode vis = root.path("visibility");
        // 观测时刻是**可选**的，这一条是 2026-10-16 在服务器上「问对象自己」问出来的：
        // GET /api/internal/qweather/current?lat=43.9&lon=125.32 返回的完整合法响应里，
        // 顶层键只有 metadata / condition / temperature / feelsLike / humidity / wind /
        // windGust / precipitation / pressure / visibility / dewPoint / cloudCover / uvIndex，
        // 而 metadata 只有 tag 与 attributions —— **没有 obsTime**。
        //
        // 以前这里写的是 requiredText(...)：首选源因此每一轮都抛「和风字段缺失:
        // metadata.obsTime」，MonitorService 按纪律降级到公共源并标 degraded:true，
        // 于是云端 /api/config/status 长期显示「首选源从未生效」。
        //
        // 不补本机时刻：freshness() 拿 time 算年龄，补一个 now() 会把「不知道有多新」
        // 变成「刚刚观测过」。缺席改为显式声明（NOT_PROVIDED_BY_PROVIDER），time 保持 null。
        String time = optionalText(root.path("metadata").path("obsTime"));
        String timeBasis = time == null
                ? WeatherSnapshot.TIME_BASIS_NOT_PROVIDED
                : WeatherSnapshot.TIME_BASIS_OBSERVED;
        double cloudCover = requiredDouble(root.path("cloudCover"), "cloudCover");
        double humidity = normalizeFraction(requiredDouble(root.path("humidity"), "humidity"), "humidity");
        double thunder = estimateThunder(c.path("code").asText(""), cloudCover);
        return new WeatherSnapshot(
                time, "live", lat, lon,
                requiredText(c.path("text"), "condition.text"),
                requiredDouble(root.path("temperature").path("value"), "temperature.value"),
                humidity,
                requiredDouble(wind.path("value"), "wind.speed.value"),
                requiredDouble(gust.path("value"), "windGust.value"),
                optionalDegree(root.path("wind").path("direction").path("degree")),
                requiredDouble(precip.path("value"), "precipitation.intensity.value"),
                requiredDouble(vis.path("value"), "visibility.value"),
                requiredDouble(root.path("pressure").path("value"), "pressure.value"),
                cloudCover,
                thunder,
                timeBasis);
    }

    /** 拉取默认作业区逐小时预报并标准化 */
    public List<ForecastHour> hourly(int hours) throws Exception {
        return hourly(hours, props.lat(), props.lon());
    }

    /** 拉取指定坐标逐小时预报并标准化 */
    public List<ForecastHour> hourly(int hours, double lat, double lon) throws Exception {
        if (hours < 1 || hours > 240) throw new IllegalArgumentException("和风预报小时数超出接口范围: " + hours);
        return parseHourly(getJson(hourlyUrl(hours, lat, lon)));
    }

    /**
     * 原始实时响应 + 单位 + 质量说明。供内部原始天气接口使用，
     * 不在这里合并成面向前端的统一状态。
     */
    public Map<String, Object> rawCurrent(double lat, double lon) throws Exception {
        checkCoordinate(lat, lon);
        JsonNode root = getJson(currentUrl(lat, lon));
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("provider", "QWEATHER");
        value.put("product", "weather/v1/current");
        value.put("requestedLocation", List.of(lat, lon));
        value.put("raw", mapper.convertValue(root, Map.class));
        value.put("units", Map.of(
                "temperature", "°C", "windSpeed", "km/h", "precipitation", "mm",
                "visibility", "km", "pressure", "hPa",
                "humidity", "fraction", "cloudCover", "fraction"));
        value.put("thunderEstimate", estimateThunder(root.path("condition").path("code").asText(""),
                root.path("cloudCover").isNumber() ? root.path("cloudCover").asDouble() : 0.0));
        value.put("thunderEstimateMethod", THUNDER_ESTIMATE_METHOD);
        value.put("qualityFlags", List.of(
                "NOT_A_STATION_OBSERVATION_CONTRACT",
                "THUNDER_VALUE_IS_DERIVED_ESTIMATE_NOT_A_PRODUCT_FIELD"));
        value.put("note", "和风不提供独立雷暴字段；thunderEstimate 由天气代码与云量推导，属于工程近似，不得当作观测雷暴概率。");
        return value;
    }

    /** 原始逐小时响应 + 单位，供内部接口使用。 */
    public Map<String, Object> rawHourly(int hours, double lat, double lon) throws Exception {
        if (hours < 1 || hours > 240) throw new IllegalArgumentException("和风预报小时数超出接口范围: " + hours);
        checkCoordinate(lat, lon);
        JsonNode root = getJson(hourlyUrl(hours, lat, lon));
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("provider", "QWEATHER");
        value.put("product", "weather/v1/hourly");
        value.put("requestedLocation", List.of(lat, lon));
        value.put("hours", hours);
        value.put("raw", mapper.convertValue(root, Map.class));
        value.put("units", Map.of("temperature", "°C", "windSpeed", "km/h", "precipitation", "mm", "visibility", "km"));
        value.put("qualityFlags", List.of("THUNDER_VALUE_IS_DERIVED_ESTIMATE_NOT_A_PRODUCT_FIELD"));
        value.put("note", "逐小时雷暴为降水概率推导值，非产品字段。");
        return value;
    }

    static String currentUrl(String host, double lat, double lon) {
        return "https://" + host + "/weather/v1/current/" + lat + "/" + lon + "?localTime=true&lang=zh";
    }

    static String hourlyUrl(String host, int hours, double lat, double lon) {
        return "https://" + host + "/weather/v1/hourly/" + lat + "/" + lon
                + "?hours=" + hours + "&localTime=true&lang=zh";
    }

    private String currentUrl(double lat, double lon) {
        return currentUrl(props.apiHost(), lat, lon);
    }

    private String hourlyUrl(int hours, double lat, double lon) {
        return hourlyUrl(props.apiHost(), hours, lat, lon);
    }

    static void checkCoordinate(double lat, double lon) {
        if (!Double.isFinite(lat) || !Double.isFinite(lon)) {
            throw new IllegalArgumentException("和风坐标必须为有限数值");
        }
        if (lat < -90 || lat > 90) throw new IllegalArgumentException("和风纬度超出范围: " + lat);
        if (lon < -180 || lon > 180) throw new IllegalArgumentException("和风经度超出范围: " + lon);
    }

    private List<ForecastHour> parseHourly(JsonNode root) {
        List<ForecastHour> list = new ArrayList<>();
        for (JsonNode h : root.path("hours")) {
            list.add(new ForecastHour(
                    requiredText(h.path("forecastTime"), "hours.forecastTime"),
                    requiredDouble(h.path("temperature").path("value"), "hours.temperature.value"),
                    requiredDouble(h.path("wind").path("speed").path("value"), "hours.wind.speed.value"),
                    requiredDouble(h.path("windGust").path("value"), "hours.windGust.value"),
                    requiredDouble(h.path("precipitation").path("intensity").path("value"), "hours.precipitation.intensity.value"),
                    requiredDouble(h.path("visibility").path("value"), "hours.visibility.value"),
                    thunderFromPrecipProb(normalizeFraction(requiredDouble(
                            h.path("precipitation").path("probability"), "hours.precipitation.probability"),
                            "hours.precipitation.probability"))));
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

    private String requiredText(JsonNode node, String field) {
        if (node == null || node.isMissingNode() || node.isNull() || node.asText().isBlank()) {
            throw new IllegalArgumentException("和风字段缺失: " + field);
        }
        return node.asText();
    }

    /**
     * 可选文本：父节点缺失、显式 null、或空串一律返回 {@code null}。
     *
     * <p>与 {@link #requiredText} 成对存在，用途只有一处：观测时刻。**不许**把它当成
     * 「宽松版 requiredText」去接其它字段 —— 每一个降为可选的字段都会让一条原本会红的
     * 判据变成沉默，而沉默与「字段本来就不存在」在日志里长得一模一样。</p>
     */
    private String optionalText(JsonNode node) {
        if (node == null || node.isMissingNode() || node.isNull()) return null;
        String text = node.asText();
        return text == null || text.isBlank() ? null : text;
    }

    private double requiredDouble(JsonNode node, String field) {
        if (node == null || node.isMissingNode() || node.isNull() || !node.isNumber()) {
            throw new IllegalArgumentException("和风数值字段缺失或格式错误: " + field);
        }
        double value = node.asDouble();
        if (!Double.isFinite(value)) throw new IllegalArgumentException("和风数值字段非有限值: " + field);
        return value;
    }

    private double normalizeFraction(double value, String field) {
        double normalized = value > 1 && value <= 100 ? value / 100.0 : value;
        if (normalized < 0 || normalized > 1) {
            throw new IllegalArgumentException("和风比例字段超出范围: " + field);
        }
        return normalized;
    }

    private Integer optionalDegree(JsonNode node) {
        if (node == null || node.isMissingNode() || node.isNull()) return null;
        if (!node.canConvertToInt()) throw new IllegalArgumentException("和风风向字段格式错误");
        int value = node.asInt();
        if (value < 0 || value > 359) throw new IllegalArgumentException("和风风向字段超出范围");
        return value;
    }

    private JsonNode getJson(String url) throws Exception {
        HttpRequest req = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(20))
                .header("Authorization", "Bearer " + jwtService.bearerToken())
                .header("Accept-Encoding", "gzip")
                .GET()
                .build();
        HttpResponse<byte[]> resp = http.send(req, HttpResponse.BodyHandlers.ofByteArray());
        byte[] body = decodeBody(resp.body(), resp.headers().firstValue("content-encoding").orElse(""));
        if (resp.statusCode() != 200) {
            log.warn("和风 API 响应 {} {}: {}", resp.statusCode(), url,
                    abbreviate(new String(body, StandardCharsets.UTF_8)));
            throw new IllegalStateException("和风 API HTTP " + resp.statusCode());
        }
        return mapper.readTree(body);
    }

    /**
     * 和风 CDN 会压缩正文。Jackson 直接解析压缩字节只会得到
     * “Illegal character (CTRL-CHAR, code 31)”，整条链路因此静默降级，
     * 所以先按 gzip 魔数解压再交给 Jackson。
     */
    static byte[] decodeBody(byte[] raw, String contentEncoding) throws IOException {
        if (raw == null) return new byte[0];
        if (raw.length < 2) return raw;
        boolean gzipMagic = (raw[0] & 0xFF) == 0x1F && (raw[1] & 0xFF) == 0x8B;
        boolean declaredGzip = contentEncoding != null
                && contentEncoding.toLowerCase(Locale.ROOT).contains("gzip");
        if (!gzipMagic) {
            if (declaredGzip) {
                log.warn("响应声明 gzip 但正文没有压缩魔数，按明文解析");
            }
            return raw;
        }
        try (GZIPInputStream in = new GZIPInputStream(new ByteArrayInputStream(raw))) {
            return in.readAllBytes();
        }
    }

    private String abbreviate(String s) {
        return s == null ? "" : s.substring(0, Math.min(200, s.length()));
    }
}
