package com.tianchuang.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.config.MonitorProperties;
import com.tianchuang.config.QweatherProperties;
import com.tianchuang.entity.AlertEntity;
import com.tianchuang.entity.MonitoringRunEntity;
import com.tianchuang.entity.SfiRecordEntity;
import com.tianchuang.entity.TrackResultEntity;
import com.tianchuang.model.FlightLevel;
import com.tianchuang.model.ForecastHour;
import com.tianchuang.model.Scenario;
import com.tianchuang.model.WeatherSnapshot;
import com.tianchuang.qweather.QweatherClient;
import com.tianchuang.repository.AlertRepo;
import com.tianchuang.repository.MonitoringRunRepo;
import com.tianchuang.repository.SfiRecordRepo;
import com.tianchuang.repository.TrackResultRepo;
import com.tianchuang.ws.DashboardWebSocketHandler;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.locks.ReentrantLock;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.core.task.TaskExecutor;
import org.springframework.stereotype.Service;

/**
 * 一轮监测只使用创建时冻结的场景和来源策略。成功提交后才改变大屏的已生效状态。
 */
@Service
public class MonitorService {
    private static final Logger log = LoggerFactory.getLogger(MonitorService.class);
    private static final int SFI_DROP_THRESHOLD = 30;
    private static final long DROP_WINDOW_MINUTES = 60;

    private final MonitorProperties monitor;
    private final QweatherProperties qw;
    private final QweatherClient qweatherClient;
    private final PythonClient python;
    private final SfiEngine sfiEngine;
    private final FusionService fusion;
    private final AlertService alertService;
    private final AlertStateService alertStates;
    private final SfiRecordRepo sfiRepo;
    private final TrackResultRepo trackRepo;
    private final AlertRepo alertRepo;
    private final MonitoringRunRepo runRepo;
    private final RunCommitService commits;
    private final DashboardWebSocketHandler ws;
    private final ObjectMapper mapper;
    private final TaskExecutor track2Executor;
    private final ReentrantLock runLock = new ReentrantLock();

    private volatile Scenario appliedScenario;

    public MonitorService(MonitorProperties monitor, QweatherProperties qw,
                          QweatherClient qweatherClient, PythonClient python,
                          SfiEngine sfiEngine, FusionService fusion, AlertService alertService,
                          AlertStateService alertStates,
                          SfiRecordRepo sfiRepo, TrackResultRepo trackRepo, AlertRepo alertRepo,
                          MonitoringRunRepo runRepo, RunCommitService commits,
                          DashboardWebSocketHandler ws, ObjectMapper mapper,
                          @Qualifier("track2Executor") TaskExecutor track2Executor) {
        this.monitor = monitor;
        this.qw = qw;
        this.qweatherClient = qweatherClient;
        this.python = python;
        this.sfiEngine = sfiEngine;
        this.fusion = fusion;
        this.alertService = alertService;
        this.alertStates = alertStates;
        this.sfiRepo = sfiRepo;
        this.trackRepo = trackRepo;
        this.alertRepo = alertRepo;
        this.runRepo = runRepo;
        this.commits = commits;
        this.ws = ws;
        this.mapper = mapper;
        this.track2Executor = track2Executor;
        this.appliedScenario = Scenario.parse(monitor.scenario());
    }

    /** 首次 6 秒，之后默认 10 分钟；两个值均按毫秒解释。 */
    @Scheduled(initialDelayString = "${monitor.initial-delay-ms:6000}",
            fixedDelayString = "${monitor.fixed-delay-ms:600000}")
    public void scheduledRun() {
        try {
            execute(appliedScenario, false);
        } catch (RunBusyException e) {
            log.info("定时监测跳过：已有监测轮正在执行");
        } catch (Exception e) {
            log.error("定时监测失败: {}", e.getMessage(), e);
        }
    }

    @EventListener(ApplicationReadyEvent.class)
    public void restoreAppliedScenario() {
        runRepo.findFirstByStatusInOrderByIdDesc(List.of("RULE_READY", "COMPLETE"))
                .map(run -> run.scenario)
                .filter(value -> value != null && !value.isBlank())
                .ifPresent(value -> {
                    try { appliedScenario = Scenario.parse(value); }
                    catch (IllegalArgumentException e) { log.warn("忽略历史运行中的未知剧本：{}", value); }
                });
    }

    public Map<String, Object> runOnce() throws Exception {
        return execute(appliedScenario, true);
    }

    public Map<String, Object> switchScenario(String rawScenario) throws Exception {
        Scenario requested = Scenario.parse(rawScenario);
        if (monitor.live()) {
            throw new IllegalArgumentException("live 模式不允许切换模拟剧本");
        }
        return execute(requested, true);
    }

    private Map<String, Object> execute(Scenario requested, boolean manual) throws Exception {
        if (!runLock.tryLock()) {
            throw new RunBusyException("已有监测轮正在执行，请稍后重试");
        }

        MonitoringRunEntity run = new MonitoringRunEntity();
        run.runId = UUID.randomUUID().toString();
        run.regionId = regionId();
        run.scenario = requested.key();
        run.configuredMode = monitor.mode();
        run.status = "RUNNING";
        run.startedAt = LocalDateTime.now();
        run.updatedAt = run.startedAt;
        try {
            commits.start(run);
            long started = System.currentTimeMillis();
            log.info("监测轮开始 runId={} mode={} scenario={} manual={}",
                    run.runId, monitor.mode(), requested.key(), manual);

            WeatherSnapshot snapshot;
            List<ForecastHour> forecast;
            if (monitor.live()) {
                try {
                    snapshot = qweatherClient.current();
                    forecast = qweatherClient.hourly(6);
                    run.effectiveSource = "live";
                } catch (Exception liveError) {
                    if (!monitor.allowSimFallback()) {
                        throw new ExternalDataUnavailableException("实时气象不可用: " + liveError.getMessage(), liveError);
                    }
                    Map<String, Object> generated = python.generateSim(requested.key(), 6);
                    snapshot = convertSnapshot(generated);
                    forecast = convertForecast(generated);
                    run.effectiveSource = "sim";
                    run.degraded = true;
                    run.degradeReason = "LIVE_SOURCE_UNAVAILABLE";
                }
            } else {
                Map<String, Object> generated = python.generateSim(requested.key(), 6);
                snapshot = convertSnapshot(generated);
                forecast = convertForecast(generated);
                run.effectiveSource = "sim";
            }
            run.obsTime = snapshot.time();
            run.ingestedAt = LocalDateTime.now();

            SfiEngine.SfiResult rule = sfiEngine.evaluate(snapshot);
            run.evaluatedAt = LocalDateTime.now();

            Map<String, Object> track2 = pendingTrack2();
            FusionService.FusionResult fused = fusion.fuse(rule.sfi(), rule.level(), null, 0);
            int fusedSfi = rule.sfi();

            SfiRecordEntity record = newRecord(run, snapshot, rule);
            TrackResultEntity track = newTrack(run.runId, rule, track2, null, fused, fusedSfi);
            track.status = "PENDING";
            Optional<SfiRecordEntity> previous = previousComparable(record);
            commits.completeWithTrack2Job(run, snapshot, forecast, record, track,
                    LocalDateTime.now().plusSeconds(20));

            appliedScenario = requested;
            checkAndAlert(run.runId, record, previous, rule, track2, fused, rule.level(), null);

            Map<String, Object> dashboard = buildDashboard();
            ws.broadcastDashboard(run.runId, dashboard);
            try {
                WeatherSnapshot submittedSnapshot = snapshot;
                List<ForecastHour> submittedForecast = List.copyOf(forecast);
                track2Executor.execute(() -> completeTrack2(run, record, submittedSnapshot,
                        submittedForecast, rule, previous));
            } catch (RejectedExecutionException rejected) {
                commits.failTrack2(run, track, "QUEUE_REJECTED", "轨2队列已满，本轮保留规则结果");
                commits.finishTrack2Job(run.runId, "FAILED", "QUEUE_REJECTED");
                dashboard = buildDashboard();
                ws.broadcastDashboard(run.runId, dashboard);
            }
            log.info("规则阶段完成 runId={} source={} SFI={} level={} costMs={}",
                    run.runId, run.effectiveSource, rule.sfi(), fused.fused(),
                    System.currentTimeMillis() - started);
            return dashboard;
        } catch (Exception e) {
            if (run.id != null && !"RULE_READY".equals(run.status) && !"COMPLETE".equals(run.status)) {
                commits.fail(run, errorCode(e), e.getMessage());
            }
            throw e;
        } finally {
            runLock.unlock();
        }
    }

    private void completeTrack2(MonitoringRunEntity run, SfiRecordEntity record,
                                WeatherSnapshot snapshot, List<ForecastHour> forecast,
                                SfiEngine.SfiResult rule, Optional<SfiRecordEntity> previous) {
        TrackResultEntity track = trackRepo.findFirstByRunIdOrderByRevisionDesc(run.runId).orElse(null);
        if (track == null) {
            commits.finishTrack2Job(run.runId, "FAILED", "TRACK_RECORD_MISSING");
            return;
        }
        try {
            var job = commits.claimTrack2Job(run.runId);
            if (job == null) return;
            long deadline = job.dueAt.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
            if (deadline <= System.currentTimeMillis()) {
                commits.failTrack2(run, track, "TIMEOUT", "轨2排队已超过总期限，本轮保留规则结果");
                commits.finishTrack2Job(run.runId, "TIMEOUT", "DEADLINE_EXCEEDED");
                Map<String, Object> timedOutDashboard = buildDashboard();
                if (run.runId.equals(timedOutDashboard.get("runId"))) {
                    ws.broadcastDashboard(run.runId, timedOutDashboard);
                }
                return;
            }
            Map<String, Object> track2 = python.track2(run.runId, deadline, snapshot, forecast,
                    qw.regionName(), qw.taskType());
            if (!rule.ruleVersion().equals(String.valueOf(track2.get("rule_version")))) {
                commits.failTrack2(run, track, "INVALID", "轨2规则版本不一致，本轮保留规则结果");
                commits.finishTrack2Job(run.runId, "INVALID", "RULE_VERSION_MISMATCH");
                Map<String, Object> invalidDashboard = buildDashboard();
                if (run.runId.equals(invalidDashboard.get("runId"))) {
                    ws.broadcastDashboard(run.runId, invalidDashboard);
                }
                return;
            }
            FlightLevel t2 = parseLevel(track2.get("risk_level")).orElse(null);
            if (t2 == null) {
                commits.failTrack2(run, track, "INVALID", "轨2返回未知等级，本轮保留规则结果");
                commits.finishTrack2Job(run.runId, "INVALID", "UNKNOWN_LEVEL");
            } else {
                double confidence = toDouble(track2.get("confidence"), 0);
                FusionService.FusionResult fused = fusion.fuse(rule.sfi(), rule.level(), t2, confidence);
                int fusedSfi = fused.fused() == rule.level() ? rule.sfi() : fused.fused().refSfi;
                applyTrack2(track, track2, t2, fused, fusedSfi);
                commits.completeTrack2(run, track);
                commits.finishTrack2Job(run.runId, "SUCCEEDED", null);
                if (isLatestCompletedRun(run.runId)) {
                    checkAndAlert(run.runId, record, previous, rule, track2, fused, rule.level(), t2);
                }
            }
        } catch (Exception e) {
            log.warn("轨2异步研判失败 runId={}: {}", run.runId, e.getMessage());
            commits.failTrack2(run, track, "UNAVAILABLE", "轨2不可用，本轮保留规则结果");
            commits.finishTrack2Job(run.runId, "UNAVAILABLE", e.getClass().getSimpleName());
        }
        Map<String, Object> dashboard = buildDashboard();
        if (run.runId.equals(dashboard.get("runId"))) {
            ws.broadcastDashboard(run.runId, dashboard);
        }
    }

    private WeatherSnapshot convertSnapshot(Map<String, Object> generated) {
        return mapper.convertValue(generated.get("snapshot"), WeatherSnapshot.class);
    }

    private List<ForecastHour> convertForecast(Map<String, Object> generated) {
        return mapper.convertValue(generated.get("hourly"),
                mapper.getTypeFactory().constructCollectionType(List.class, ForecastHour.class));
    }

    private SfiRecordEntity newRecord(MonitoringRunEntity run, WeatherSnapshot s, SfiEngine.SfiResult rule) {
        SfiRecordEntity e = new SfiRecordEntity();
        e.runId = run.runId;
        e.regionId = run.regionId;
        e.configuredMode = run.configuredMode;
        e.effectiveSource = run.effectiveSource;
        e.degraded = run.degraded;
        e.degradeReason = run.degradeReason;
        e.obsTime = s.time();
        e.ingestedAt = run.ingestedAt;
        e.evaluatedAt = run.evaluatedAt;
        e.source = s.source();
        e.scenario = "sim".equals(run.effectiveSource) ? run.scenario : null;
        e.sfi = rule.sfi();
        e.rawSfi = rule.rawSfi();
        e.level = rule.level().name();
        e.hardBan = rule.hardBan();
        e.ruleVersion = rule.ruleVersion();
        e.lat = s.lat();
        e.lon = s.lon();
        e.conditionText = s.conditionText();
        e.windSpeed = s.windSpeed();
        e.windGust = s.windGust();
        e.windDeg = s.windDeg();
        e.precipMmh = s.precipMmh();
        e.visibilityM = s.visibilityM();
        e.thunderProb = s.thunderProb();
        e.tempC = s.tempC();
        e.humidity = s.humidity();
        e.pressureHpa = s.pressureHpa();
        e.cloudCover = s.cloudCover();
        try {
            e.checksJson = mapper.writeValueAsString(sfiEngine.toMap(rule).get("checks"));
        } catch (Exception ignored) {
            e.checksJson = "[]";
        }
        return e;
    }

    private TrackResultEntity newTrack(String runId, SfiEngine.SfiResult rule,
                                       Map<String, Object> track2, FlightLevel t2,
                                       FusionService.FusionResult fused, int fusedSfi) {
        TrackResultEntity e = new TrackResultEntity();
        e.runId = runId;
        e.track1Level = rule.level().name();
        e.track1Sfi = rule.sfi();
        e.track1Reason = reasonsFromChecks(rule);
        e.track2Level = t2 == null ? null : t2.name();
        e.track2Confidence = t2 == null ? 0 : toDouble(track2.get("confidence"), 0);
        e.track2Source = String.valueOf(track2.get("source"));
        e.track2Factors = stringify(track2.get("key_factors"));
        e.track2Advice = stringify(track2.get("advice"));
        e.fusedLevel = fused.fused().name();
        e.agreement = fused.agreement().name();
        e.fusedSfi = fusedSfi;
        return e;
    }

    private void applyTrack2(TrackResultEntity track, Map<String, Object> result, FlightLevel level,
                             FusionService.FusionResult fused, int fusedSfi) {
        track.track2Level = level.name();
        track.track2Confidence = toDouble(result.get("confidence"), 0);
        track.track2Source = stringify(result.get("source"));
        track.track2Factors = stringify(result.get("key_factors"));
        track.track2Advice = stringify(result.get("advice"));
        track.fusedLevel = fused.fused().name();
        track.agreement = fused.agreement().name();
        track.fusedSfi = fusedSfi;
    }

    private Optional<SfiRecordEntity> previousComparable(SfiRecordEntity record) {
        OffsetDateTime current = observationTime(record).orElse(null);
        if (current == null) return Optional.empty();
        return sfiRepo.findTop10ByRegionIdAndEffectiveSourceAndRuleVersionAndScenarioOrderByTsDesc(
                        record.regionId, record.effectiveSource, record.ruleVersion, record.scenario).stream()
                .filter(candidate -> observationTime(candidate).map(time -> time.isBefore(current)).orElse(false))
                .findFirst();
    }

    private void checkAndAlert(String runId, SfiRecordEntity current, Optional<SfiRecordEntity> previous,
                               SfiEngine.SfiResult rule, Map<String, Object> track2,
                               FusionService.FusionResult fused, FlightLevel t1, FlightLevel t2) {
        boolean levelReach = fused.fused() == FlightLevel.DANGER || fused.fused() == FlightLevel.BAN;
        boolean sfiDrop = previous.filter(p -> {
            Optional<OffsetDateTime> before = observationTime(p);
            Optional<OffsetDateTime> after = observationTime(current);
            if (before.isEmpty() || after.isEmpty()) return false;
            Duration elapsed = Duration.between(before.get(), after.get());
            return !elapsed.isNegative() && elapsed.compareTo(Duration.ofMinutes(DROP_WINDOW_MINUTES)) <= 0
                    && p.sfi - current.sfi >= SFI_DROP_THRESHOLD;
        }).isPresent();
        processAlertState("LEVEL_REACH", levelReach, runId, current, rule, track2, fused, t1, t2);
        processAlertState("SFI_DROP", sfiDrop, runId, current, rule, track2, fused, t1, t2);
    }

    private Optional<OffsetDateTime> observationTime(SfiRecordEntity record) {
        try { return Optional.of(OffsetDateTime.parse(record.obsTime)); }
        catch (Exception ignored) { return Optional.empty(); }
    }

    private void processAlertState(String trigger, boolean active, String runId,
                                   SfiRecordEntity current, SfiEngine.SfiResult rule,
                                   Map<String, Object> track2, FusionService.FusionResult fused,
                                   FlightLevel t1, FlightLevel t2) {
        String key = String.join("|", current.regionId, current.effectiveSource, rule.ruleVersion(),
                current.scenario == null ? "live" : current.scenario, trigger);
        long runSequence = runRepo.findByRunId(runId).map(r -> r.id).orElse(-1L);
        AlertStateService.Decision decision = alertStates.evaluate(key, runSequence, active, fused.fused());
        if (decision.action() != AlertStateService.Action.NONE) {
            alertService.createAlert(decision.level(), trigger, current, rule, track2,
                    fused, t1, t2, decision);
        }
    }

    private boolean isLatestCompletedRun(String runId) {
        return runRepo.findFirstByStatusInOrderByIdDesc(List.of("RULE_READY", "COMPLETE"))
                .map(run -> runId.equals(run.runId)).orElse(false);
    }

    public Map<String, Object> buildDashboard() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("version", 1);
        out.put("serverTime", LocalDateTime.now().toString());
        out.put("configuredMode", monitor.mode());
        out.put("mode", monitor.mode()); // 前端过渡兼容
        out.put("regionId", regionId());
        out.put("region", qw.regionName());
        out.put("taskType", qw.taskType());

        Optional<MonitoringRunEntity> completed = runRepo.findFirstByRegionIdAndConfiguredModeAndStatusInOrderByIdDesc(
                regionId(), monitor.mode(), List.of("RULE_READY", "COMPLETE"));
        Optional<MonitoringRunEntity> latestAttempt = runRepo.findFirstByRegionIdAndConfiguredModeOrderByIdDesc(regionId(), monitor.mode());
        if (completed.isEmpty()) {
            out.put("runId", null);
            out.put("runSequence", 0);
            out.put("revision", 0);
            out.put("status", "WAITING");
            out.put("dataStatus", "NO_DATA");
            out.put("scenario", appliedScenario.key());
            out.put("appliedScenario", appliedScenario.key());
            out.put("current", null);
            out.put("forecast", List.of());
            out.put("forecastSfi", List.of());
        } else {
            MonitoringRunEntity run = completed.get();
            out.put("runId", run.runId);
            out.put("runSequence", run.id);
            out.put("revision", run.revision);
            out.put("status", run.status);
            out.put("effectiveSource", run.effectiveSource);
            out.put("degraded", run.degraded);
            out.put("degradeReason", run.degradeReason);
            out.put("scenario", run.scenario);
            out.put("appliedScenario", run.scenario);
            out.put("obsTime", run.obsTime);
            out.put("updatedAt", value(run.updatedAt));
            out.put("lastRunAt", value(run.updatedAt));
            out.put("dataStatus", freshness(run.obsTime));
            List<ForecastHour> forecast = readForecast(run.forecastJson);
            out.put("forecast", forecast);
            out.put("forecastSfi", forecastSfi(forecast));
            sfiRepo.findFirstByRunId(run.runId).ifPresent(e -> addCurrent(out, e));
        }

        latestAttempt.ifPresent(run -> out.put("lastAttempt", Map.of(
                "runId", run.runId,
                "status", run.status,
                "errorCode", value(run.errorCode),
                "message", value(run.errorMessage),
                "updatedAt", value(run.updatedAt))));
        if (latestAttempt.isEmpty()) out.put("lastAttempt", null);
        out.put("lastError", latestAttempt.filter(r -> "FAILED".equals(r.status)).map(r -> r.errorMessage).orElse(null));

        String historyRuleVersion = out.get("current") instanceof Map<?, ?> current ? String.valueOf(current.get("ruleVersion")) : "unknown";
        List<SfiRecordEntity> scopedHistory = sfiRepo.findTop48ByRegionIdAndEffectiveSourceAndRuleVersionAndScenarioOrderByTsDesc(
                regionId(), String.valueOf(out.getOrDefault("effectiveSource", "unavailable")), historyRuleVersion,
                String.valueOf(out.getOrDefault("appliedScenario", "clear")));
        List<String> historyRunIds = scopedHistory.stream().map(e -> e.runId).filter(java.util.Objects::nonNull).toList();
        out.put("sfiHistory", scopedHistory.stream().map(this::historyMap).toList());
        List<TrackResultEntity> tracks = completed.flatMap(r -> trackRepo.findFirstByRunIdOrderByRevisionDesc(r.runId))
                .map(List::of).orElseGet(List::of);
        out.put("tracks", tracks.stream().map(this::trackMap).toList());
        out.put("tracksHistory", historyRunIds.isEmpty() ? List.of() : trackRepo.findTop48ByRunIdInOrderByTsDesc(historyRunIds).stream().map(this::trackMap).toList());
        out.put("alerts", historyRunIds.isEmpty() ? List.of() : alertRepo.findTop20ByRunIdInOrderByTsDesc(historyRunIds).stream().map(this::alertMap).toList());
        return out;
    }

    private void addCurrent(Map<String, Object> out, SfiRecordEntity e) {
        Map<String, Object> snapshot = new LinkedHashMap<>();
        snapshot.put("time", e.obsTime);
        snapshot.put("source", e.effectiveSource);
        snapshot.put("lat", e.lat);
        snapshot.put("lon", e.lon);
        snapshot.put("conditionText", e.conditionText);
        snapshot.put("tempC", e.tempC);
        snapshot.put("humidity", e.humidity);
        snapshot.put("windSpeed", e.windSpeed);
        snapshot.put("windGust", e.windGust);
        snapshot.put("windDeg", e.windDeg);
        snapshot.put("precipMmh", e.precipMmh);
        snapshot.put("visibilityM", e.visibilityM);
        snapshot.put("pressureHpa", e.pressureHpa);
        snapshot.put("cloudCover", e.cloudCover);
        snapshot.put("thunderProb", e.thunderProb);

        Map<String, Object> current = new LinkedHashMap<>();
        current.put("runId", e.runId);
        current.put("sfi", e.sfi);
        current.put("rawSfi", e.rawSfi);
        current.put("level", e.level);
        current.put("hardBan", e.hardBan);
        current.put("ruleVersion", e.ruleVersion);
        current.put("source", e.effectiveSource);
        current.put("scenario", e.scenario);
        current.put("ts", value(e.evaluatedAt));
        current.put("obsTime", e.obsTime);
        current.put("snapshot", snapshot);
        try {
            current.put("checks", mapper.readTree(e.checksJson == null ? "[]" : e.checksJson));
        } catch (Exception ex) {
            current.put("checks", List.of());
        }
        out.put("current", current);
        out.put("lat", e.lat);
        out.put("lon", e.lon);
    }

    private Map<String, Object> historyMap(SfiRecordEntity e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("runId", e.runId);
        m.put("ts", value(e.evaluatedAt != null ? e.evaluatedAt : e.ts));
        m.put("sfi", e.sfi);
        m.put("level", e.level);
        m.put("scenario", e.scenario);
        return m;
    }

    private Map<String, Object> trackMap(TrackResultEntity e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("runId", e.runId);
        m.put("revision", e.revision);
        m.put("status", e.status);
        m.put("ts", value(e.ts));
        m.put("track1Level", e.track1Level);
        m.put("track1Sfi", e.track1Sfi);
        m.put("track1Reason", e.track1Reason);
        m.put("track2Level", e.track2Level);
        m.put("track2Confidence", e.track2Confidence);
        m.put("track2Source", e.track2Source);
        m.put("track2Factors", e.track2Factors);
        m.put("track2Advice", e.track2Advice);
        m.put("fusedLevel", e.fusedLevel);
        m.put("agreement", e.agreement);
        m.put("fusedSfi", e.fusedSfi);
        return m;
    }

    private Map<String, Object> alertMap(AlertEntity e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", e.id);
        m.put("runId", e.runId);
        m.put("ts", value(e.ts));
        m.put("level", e.level);
        m.put("triggerType", e.triggerType);
        m.put("region", e.region);
        m.put("factors", e.factors);
        m.put("advice", e.advice);
        m.put("text", e.text);
        m.put("status", e.status);
        return m;
    }

    private List<ForecastHour> readForecast(String json) {
        if (json == null || json.isBlank()) return List.of();
        try {
            return mapper.readValue(json, new TypeReference<>() {});
        } catch (Exception e) {
            log.warn("读取预报快照失败: {}", e.getMessage());
            return List.of();
        }
    }

    private List<Map<String, Object>> forecastSfi(List<ForecastHour> forecast) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (ForecastHour h : forecast) {
            try {
                WeatherSnapshot synthetic = new WeatherSnapshot(h.time(), "forecast", qw.lat(), qw.lon(),
                        "预报", h.tempC(), 0.65, h.windSpeed(), h.windGust(), null,
                        h.precipMmh(), h.visibilityM(), 1010.0, 0.8, h.thunderProb());
                SfiEngine.SfiResult r = sfiEngine.evaluate(synthetic);
                result.add(Map.of("time", h.time(), "sfi", r.sfi(), "level", r.level().name(),
                        "levelLabel", r.level().label));
            } catch (Exception e) {
                log.warn("预报点无效 time={}: {}", h.time(), e.getMessage());
            }
        }
        return result;
    }

    private String freshness(String obsTime) {
        if (obsTime == null) return "UNKNOWN";
        try {
            long age = Duration.between(OffsetDateTime.parse(obsTime), OffsetDateTime.now()).toMinutes();
            return age >= 0 && age <= Math.max(20, monitor.fixedDelayMs() / 30_000) ? "FRESH" : "STALE";
        } catch (Exception ignored) {
            return "UNKNOWN";
        }
    }

    private Map<String, Object> unavailableTrack2() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("risk_level", null);
        m.put("confidence", 0);
        m.put("key_factors", List.of("轨2服务不可用"));
        m.put("advice", "本轮仅采用轨1规则研判");
        m.put("alert_text", "");
        m.put("source", "unavailable");
        return m;
    }

    private Map<String, Object> pendingTrack2() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("risk_level", null);
        m.put("confidence", 0);
        m.put("key_factors", List.of("轨2研判中"));
        m.put("advice", "");
        m.put("source", "pending");
        return m;
    }

    private Optional<FlightLevel> parseLevel(Object raw) {
        if (raw == null) return Optional.empty();
        String text = String.valueOf(raw).trim();
        for (FlightLevel value : FlightLevel.values()) {
            if (value.name().equalsIgnoreCase(text) || value.label.equals(text)) return Optional.of(value);
        }
        return Optional.empty();
    }

    private String reasonsFromChecks(SfiEngine.SfiResult result) {
        List<String> reasons = result.checks().stream().filter(c -> c.banned() || c.warn())
                .map(c -> c.factor() + " " + c.value() + c.unit() + "（" + c.note() + "）").toList();
        return reasons.isEmpty() ? "各要素均在适飞阈值内" : String.join("；", reasons);
    }

    private double toDouble(Object value, double fallback) {
        if (value instanceof Number n) return n.doubleValue();
        try {
            return value == null ? fallback : Double.parseDouble(String.valueOf(value));
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private String stringify(Object value) {
        if (value == null) return "";
        if (value instanceof List<?> list) return String.join("；", list.stream().map(String::valueOf).toList());
        return String.valueOf(value);
    }

    private String value(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private String regionId() {
        return qw.regionName() == null || qw.regionName().isBlank() ? "default" : qw.regionName();
    }

    private String errorCode(Exception e) {
        if (e instanceof ExternalDataUnavailableException) return "LIVE_SOURCE_UNAVAILABLE";
        if (e instanceof IllegalArgumentException) return "INVALID_INPUT";
        return "MONITOR_FAILED";
    }

    public static class RunBusyException extends IllegalStateException {
        public RunBusyException(String message) { super(message); }
    }

    public static class ExternalDataUnavailableException extends IllegalStateException {
        public ExternalDataUnavailableException(String message, Throwable cause) { super(message, cause); }
    }
}
