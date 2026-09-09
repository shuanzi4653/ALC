package com.tianchuang.service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.TimeUnit;

import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.tianchuang.config.MonitorProperties;
import com.tianchuang.config.QweatherProperties;
import com.tianchuang.entity.AlertEntity;
import com.tianchuang.entity.SfiRecordEntity;
import com.tianchuang.entity.TrackResultEntity;
import com.tianchuang.model.FlightLevel;
import com.tianchuang.model.ForecastHour;
import com.tianchuang.model.WeatherSnapshot;
import com.tianchuang.qweather.QweatherClient;
import com.tianchuang.repository.AlertRepo;
import com.tianchuang.repository.SfiRecordRepo;
import com.tianchuang.repository.TrackResultRepo;
import com.tianchuang.ws.DashboardWebSocketHandler;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

/**
 * 监测编排服务（对应计划书 8.1 实时运行流程）：
 * 数据获取 → 轨1 规则研判 → 轨2 LLM 研判 → 双轨融合 → 落库 → 骤变检测 → 预警推送 → 大屏广播
 */
@Service
public class MonitorService {

    private static final Logger log = LoggerFactory.getLogger(MonitorService.class);
    private static final double SFI_DROP_THRESHOLD = 30;    // 骤变阈值（分）
    private static final long DROP_WINDOW_MINUTES = 60;     // 骤变时间窗
    private static final long RUN_THROTTLE_MS = 3000;       // 手动触发节流窗口

    /** 最近一次 runOnce 时间戳（防手动连点堆积 DeepSeek 调用） */
    private volatile long lastRunMillis = 0;

    private final MonitorProperties monitor;
    private final QweatherProperties qw;
    private final QweatherClient qweatherClient;
    private final PythonClient python;
    private final SfiEngine sfiEngine;
    private final FusionService fusion;
    private final AlertService alertService;
    private final SfiRecordRepo sfiRepo;
    private final TrackResultRepo trackRepo;
    private final AlertRepo alertRepo;
    private final DashboardWebSocketHandler ws;
    /** 支持 LocalDateTime 序列化（WS 广播含实体 ts 字段）；宽容未知字段 */
    private final ObjectMapper mapper = new ObjectMapper()
            .registerModule(new JavaTimeModule())
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS)
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    /** 最近一轮的预报序列与剧本（内存态，供大屏展示） */
    private volatile List<ForecastHour> lastForecast = List.of();
    private volatile String currentScenario;
    private volatile String lastError;
    private volatile LocalDateTime lastRunAt;

    public MonitorService(MonitorProperties monitor, QweatherProperties qw,
                          QweatherClient qweatherClient, PythonClient python,
                          SfiEngine sfiEngine, FusionService fusion, AlertService alertService,
                          SfiRecordRepo sfiRepo, TrackResultRepo trackRepo, AlertRepo alertRepo,
                          DashboardWebSocketHandler ws) {
        this.monitor = monitor;
        this.qw = qw;
        this.qweatherClient = qweatherClient;
        this.python = python;
        this.sfiEngine = sfiEngine;
        this.fusion = fusion;
        this.alertService = alertService;
        this.sfiRepo = sfiRepo;
        this.trackRepo = trackRepo;
        this.alertRepo = alertRepo;
        this.ws = ws;
        this.currentScenario = monitor.scenario();
    }

    /** 定时监测（间隔分钟数来自 monitor.interval-minutes，默认 10 分钟） */
    @Scheduled(initialDelay = 6000, fixedDelayString = "${monitor.interval-minutes:10}", timeUnit = TimeUnit.MINUTES)
    public void scheduledRun() {
        try {
            runOnce();
        } catch (Exception e) {
            lastError = e.getMessage();
            log.error("定时监测失败: {}", e.getMessage(), e);
        }
    }

    /** 手动立即触发一轮（距上一轮完成不足 3 秒时直接返回最新结果，防止连点堆积 LLM 调用） */
    public synchronized Map<String, Object> runOnce() throws Exception {
        if (lastRunMillis > 0 && System.currentTimeMillis() - lastRunMillis < RUN_THROTTLE_MS) {
            log.info("手动触发被节流：距上一轮完成不足 {} ms，返回最新快照", RUN_THROTTLE_MS);
            return buildDashboard();
        }
        log.info("======== 开始监测轮 [mode={}] ========", monitor.mode());
        long t0 = System.currentTimeMillis();

        // 1. 数据获取（live=和风 API / sim=模拟生成器），失败自动降级到模拟模式
        WeatherSnapshot snap;
        String scenarioUsed = null;
        try {
            if (monitor.live()) {
                snap = qweatherClient.current();
                lastForecast = qweatherClient.hourly(6);
                log.info("数据源：和风实时 API");
            } else {
                throw new IllegalStateException("sim 模式");
            }
        } catch (Exception e) {
            if (monitor.live()) {
                log.warn("和风 API 不可用（{}），本轮降级为模拟数据", e.getMessage());
            }
            Map<String, Object> sim = python.generateSim(currentScenario, 6);
            snap = mapper.convertValue(sim.get("snapshot"), WeatherSnapshot.class);
            lastForecast = mapper.convertValue(
                    sim.get("hourly"),
                    mapper.getTypeFactory().constructCollectionType(List.class, ForecastHour.class));
            scenarioUsed = currentScenario;
        }

        // 2. 轨1：规则基线
        SfiEngine.SfiResult sfiResult = sfiEngine.evaluate(snap);

        // 3. 轨2：LLM 智能体（未配置/失败时 Python 侧自动降级；Python 服务不可用时本轮以轨1为准）
        Map<String, Object> track2;
        try {
            track2 = python.track2(snap, lastForecast, qw.regionName(), qw.taskType());
        } catch (Exception e) {
            log.warn("轨2 智能体不可用（{}），本轮融合以轨1规则结果为准", e.getMessage());
            track2 = Map.of(
                    "risk_level", sfiResult.level().label,
                    "confidence", 0.3,
                    "key_factors", "轨2服务不可用，采用轨1规则研判",
                    "advice", "请检查 Python 智能服务（端口 8600）是否启动",
                    "alert_text", "", "source", "unavailable");
        }

        // 4. 双轨融合
        FlightLevel t1 = sfiResult.level();
        FlightLevel t2 = parseLevel((String) track2.get("risk_level"));
        double t2Conf = toDouble(track2.get("confidence"), 0.5);
        FusionService.FusionResult fr = fusion.fuse(sfiResult.sfi(), t1, t2, t2Conf);
        int fusedSfi = fr.fused().refSfi;

        // 5. 落库
        SfiRecordEntity rec = saveSfi(snap, sfiResult, scenarioUsed);
        TrackResultEntity tr = saveTrack(sfiResult, track2, t1, t2, fr, fusedSfi);

        // 6. 骤变检测 + 等级触发预警
        AlertEntity alert = checkAndAlert(rec, sfiResult, track2, fr, t1, t2);

        lastRunAt = LocalDateTime.now();
        lastError = null;
        lastRunMillis = System.currentTimeMillis();
        long cost = System.currentTimeMillis() - t0;
        log.info("监测轮完成：SFI={} 轨1={} 轨2={}({}) 融合={}({}) 耗时{}ms",
                sfiResult.sfi(), t1.label, t2.label, track2.get("source"),
                fr.fused().label, fr.agreement(), cost);

        // 7. 广播大屏
        Map<String, Object> dash = buildDashboard();
        ws.broadcast(mapper.writeValueAsString(dash));
        return dash;
    }

    /** 切换模拟剧本并立即触发一轮 */
    public void switchScenario(String scenario) throws Exception {
        this.currentScenario = scenario;
        // 剧本切换必须立即生效：解除手动触发节流，强制完整跑一轮
        lastRunMillis = 0;
        runOnce();
    }

    // ---------------- 内部步骤 ----------------

    private SfiRecordEntity saveSfi(WeatherSnapshot snap, SfiEngine.SfiResult r, String scenario) {
        SfiRecordEntity e = new SfiRecordEntity();
        e.source = snap.source();
        e.scenario = scenario;
        e.sfi = r.sfi();
        e.level = r.level().name();
        e.windSpeed = snap.windSpeed();
        e.windGust = snap.windGust();
        e.precipMmh = snap.precipMmh();
        e.visibilityM = snap.visibilityM();
        e.thunderProb = snap.thunderProb();
        e.tempC = snap.tempC();
        e.humidity = snap.humidity();
        try {
            e.checksJson = mapper.writeValueAsString(sfiEngine.toMap(r).get("checks"));
        } catch (Exception ignore) {
            e.checksJson = "[]";
        }
        return sfiRepo.save(e);
    }

    private TrackResultEntity saveTrack(SfiEngine.SfiResult sfi, Map<String, Object> track2,
                                        FlightLevel t1, FlightLevel t2,
                                        FusionService.FusionResult fr, int fusedSfi) {
        TrackResultEntity e = new TrackResultEntity();
        e.track1Level = t1.name();
        e.track1Sfi = sfi.sfi();
        e.track1Reason = reasonsFromChecks(sfi);
        e.track2Level = t2.name();
        e.track2Confidence = toDouble(track2.get("confidence"), 0.5);
        e.track2Source = String.valueOf(track2.get("source"));
        e.track2Factors = String.valueOf(track2.get("key_factors"));
        e.track2Advice = String.valueOf(track2.get("advice"));
        e.fusedLevel = fr.fused().name();
        e.agreement = fr.agreement().name();
        e.fusedSfi = fusedSfi;
        return trackRepo.save(e);
    }

    private AlertEntity checkAndAlert(SfiRecordEntity rec, SfiEngine.SfiResult sfi,
                                      Map<String, Object> track2,
                                      FusionService.FusionResult fr,
                                      FlightLevel t1, FlightLevel t2) {
        // 触发条件 1：融合等级达危险/禁飞
        boolean levelReach = fr.fused() == FlightLevel.DANGER || fr.fused() == FlightLevel.BAN;
        // 触发条件 2：适飞指数骤降（与上一轮比较，时间窗内下降 ≥30 分）
        boolean sfiDrop = false;
        var prev = sfiRepo.findFirstByOrderByTsDesc();
        if (prev.isPresent() && prev.get().id != rec.id) {
            long gapMin = Duration.between(prev.get().ts, rec.ts).toMinutes();
            if (gapMin <= DROP_WINDOW_MINUTES
                    && prev.get().sfi - rec.sfi >= SFI_DROP_THRESHOLD) {
                sfiDrop = true;
            }
        }
        if (!levelReach && !sfiDrop) {
            return null;
        }
        String trigger = levelReach ? "LEVEL_REACH" : "SFI_DROP";
        return alertService.createAlert(fr.fused(), trigger, rec, sfi, track2, fr, t1, t2);
    }

    private String reasonsFromChecks(SfiEngine.SfiResult r) {
        List<String> bad = new ArrayList<>();
        for (SfiEngine.Check c : r.checks()) {
            if (c.banned() || c.warn()) {
                bad.add(c.factor() + " " + c.value() + c.unit() + "（" + c.note() + "）");
            }
        }
        return bad.isEmpty() ? "各要素均在适飞阈值内" : String.join("；", bad);
    }

    private FlightLevel parseLevel(String s) {
        if (s == null) return FlightLevel.FIT;
        for (FlightLevel l : FlightLevel.values()) {
            if (l.label.equals(s.trim()) || l.name().equalsIgnoreCase(s.trim())) {
                return l;
            }
        }
        return FlightLevel.FIT;
    }

    private double toDouble(Object o, double def) {
        if (o instanceof Number n) return n.doubleValue();
        try {
            return o == null ? def : Double.parseDouble(String.valueOf(o));
        } catch (NumberFormatException e) {
            return def;
        }
    }

    // ---------------- 大屏快照 ----------------

    /** 组装大屏全量快照（REST 与 WebSocket 共用） */
    public Map<String, Object> buildDashboard() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("serverTime", LocalDateTime.now().toString());
        m.put("mode", monitor.mode());
        m.put("scenario", currentScenario);
        m.put("region", qw.regionName());
        m.put("taskType", qw.taskType());
        m.put("lat", qw.lat());
        m.put("lon", qw.lon());
        m.put("lastRunAt", String.valueOf(lastRunAt));
        m.put("lastError", lastError);

        var latestSfi = sfiRepo.findFirstByOrderByTsDesc();
        latestSfi.ifPresent(e -> {
            Map<String, Object> sfi = new LinkedHashMap<>();
            sfi.put("sfi", e.sfi);
            sfi.put("level", e.level);
            sfi.put("source", e.source);
            sfi.put("scenario", e.scenario);
            sfi.put("ts", e.ts.toString());
            sfi.put("snapshot", Map.of(
                    "tempC", e.tempC, "humidity", e.humidity, "windSpeed", e.windSpeed,
                    "windGust", e.windGust, "precipMmh", e.precipMmh,
                    "visibilityM", e.visibilityM, "thunderProb", e.thunderProb));
            try {
                sfi.put("checks", mapper.readTree(e.checksJson == null ? "[]" : e.checksJson));
            } catch (Exception ex) {
                sfi.put("checks", List.of());
            }
            m.put("current", sfi);
        });

        m.put("sfiHistory", sfiRepo.findTop48ByOrderByTsDesc().stream()
                .map(e -> Map.of("ts", e.ts.toString(), "sfi", e.sfi, "level", e.level,
                        "scenario", e.scenario == null ? "" : e.scenario))
                .toList());

        var latestTrack = trackRepo.findTop48ByOrderByTsDesc();
        m.put("tracks", latestTrack.stream().limit(1).toList());
        m.put("tracksHistory", latestTrack);

        m.put("forecast", lastForecast);

        // 未来 0-6h 适飞指数预测（复用轨1规则引擎逐时评估）
        List<Map<String, Object>> forecastSfi = new ArrayList<>();
        for (ForecastHour fh : lastForecast) {
            WeatherSnapshot fs = new WeatherSnapshot(fh.time(), "forecast", qw.lat(), qw.lon(),
                    "", fh.tempC(), 0.65, fh.windSpeed(), fh.windGust(), 200,
                    fh.precipMmh(), fh.visibilityM(), 1010.0, 0.8, fh.thunderProb());
            SfiEngine.SfiResult fr2 = sfiEngine.evaluate(fs);
            Map<String, Object> fm = new LinkedHashMap<>();
            fm.put("time", fh.time());
            fm.put("sfi", fr2.sfi());
            fm.put("level", fr2.level().name());
            fm.put("levelLabel", fr2.level().label);
            forecastSfi.add(fm);
        }
        m.put("forecastSfi", forecastSfi);

        m.put("alerts", alertRepo.findTop20ByOrderByTsDesc());
        return m;
    }
}
