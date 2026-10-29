package com.tianchuang.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.JsonNode;
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
import java.util.concurrent.ConcurrentHashMap;
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

    /**
     * 全机默认运行口径：来自配置，并可由历史运行恢复出来。
     * <b>它不是"当前情景"</b> —— 那是每个工作区自己的一份，见 {@link #appliedScenarios}。
     */
    private volatile Scenario defaultScenario;

    /**
     * 每个匿名工作区自己选择的运行口径。
     *
     * <p>为什么不能只有一个字段：界面没有登录门之后，两个人打开的是同一个进程，
     * 「运行情景」是 <b>A 的选择</b>。用一个字段，A 一切换就会把 B 的屏幕也换掉 ——
     * 而两块屏幕上写的都是"当前情景：clear"，看不出是谁改了谁。</p>
     *
     * <p>淘汰策略：工作区号由前端随机生成，不认识的 id 能把这张表撑大。上限 64 加"踢掉
     * 最早插入的那个"够用，且不需要任何清理线程。</p>
     */
    private static final int MAX_WORKSPACES = 64;
    private final Map<String, Scenario> appliedScenarios = new ConcurrentHashMap<>();

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
        this.defaultScenario = Scenario.parse(monitor.scenario());
    }

    /** 当前调用方的工作区口径；未带标识时就是全机默认。 */
    private Scenario applied() {
        return applied(com.tianchuang.config.WorkspaceContext.current());
    }

    private Scenario applied(String workspace) {
        if (workspace == null || workspace.isBlank()) {
            return defaultScenario;
        }
        return appliedScenarios.getOrDefault(workspace, defaultScenario);
    }

    /**
     * 记下"这个工作区现在的口径"。
     *
     * <p>未标识的调用方（定时轮、巡检探针、curl）改的是全机默认 —— 这正是改造前的行为，
     * 也是"没带标识 ⇒ 一切照旧"这条判据在 Java 侧的落点。</p>
     */
    private void remember(Scenario requested) {
        String workspace = com.tianchuang.config.WorkspaceContext.current();
        if (workspace == null || workspace.isBlank()) {
            defaultScenario = requested;
            return;
        }
        if (appliedScenarios.size() >= MAX_WORKSPACES && !appliedScenarios.containsKey(workspace)) {
            appliedScenarios.keySet().stream().findFirst().ifPresent(appliedScenarios::remove);
        }
        appliedScenarios.put(workspace, requested);
    }

    /**
     * 把大屏快照推给每个在线工作区，<b>各算一次</b>。
     *
     * <p>载荷里带 {@code appliedScenario}，并且按它选出那一轮数据 —— 两个人各自切了不同
     * 情景时，载荷本来就不同。给所有人推同一份，等于把 A 的选择画到 B 的屏幕上。</p>
     */
    private void broadcastDashboard(String runId) {
        for (String workspace : ws.onlineWorkspaces()) {
            Map<String, Object> payload = com.tianchuang.config.WorkspaceContext.call(workspace, this::buildDashboard);
            ws.broadcastDashboardTo(workspace, runId, payload);
        }
    }

    /** 首次 6 秒，之后默认 10 分钟；两个值均按毫秒解释。 */
    @Scheduled(initialDelayString = "${monitor.initial-delay-ms:6000}",
            fixedDelayString = "${monitor.fixed-delay-ms:600000}")
    public void scheduledRun() {
        try {
            execute(applied(), false);
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
                    try { defaultScenario = Scenario.parse(value); }
                    catch (IllegalArgumentException e) { log.warn("忽略历史运行中的未知剧本：{}", value); }
                });
    }

    public Map<String, Object> runOnce() throws Exception {
        return execute(applied(), true);
    }

    public Map<String, Object> switchScenario(String rawScenario) throws Exception {
        // There is no longer a "simulation mode" to be in or out of: every
        // scenario is a statement about real weather availability. Switching is
        // therefore always allowed, and always reads the same real source.
        return execute(Scenario.parse(rawScenario), true);
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
            if (requested.needsWeather()) {
                // Real weather, from a real source. The Java-side preference order
                // is QWeather first (higher cadence); if it is not configured or
                // fails, the run degrades explicitly to the public model source
                // rather than to a locally invented field. Both branches record
                // which provider actually produced the values.
                try {
                    snapshot = qweatherClient.current();
                    forecast = qweatherClient.hourly(6);
                    run.effectiveSource = "live";
                } catch (Exception liveError) {
                    Map<String, Object> fetched;
                    try {
                        fetched = python.currentWeather(6);
                    } catch (Exception fallbackError) {
                        // No real source at all. Fail the round; never substitute.
                        throw new ExternalDataUnavailableException(
                                "真实气象不可用（和风失败：" + liveError.getMessage()
                                        + "；公共源失败：" + fallbackError.getMessage() + "）",
                                fallbackError);
                    }
                    snapshot = convertSnapshot(fetched);
                    forecast = convertForecast(fetched);
                    run.effectiveSource = "live-public";
                    run.degraded = true;
                    run.degradeReason = "QWEATHER_UNAVAILABLE_PUBLIC_SOURCE_USED";
                }
            } else {
                // CLEAR / UNKNOWN 不作任何气象声明，因此不取气象，也不编造。
                // 快照各要素均为 null：校验层放行缺席，规则层对每个缺席要素弃权，
                // 结果是「无要素可扣分」——SFI 保持满分而不被伪造成危险。
                // 缺席不等于安全，只是这里**没有可判的东西**；面板按 effectiveSource=none 如实标注。
                snapshot = absentSnapshot();
                forecast = List.of();
                run.effectiveSource = "none";
                if (requested == Scenario.UNKNOWN) {
                    run.degraded = true;
                    run.degradeReason = "WEATHER_SOURCE_UNAVAILABLE";
                }
            }
            run.obsTime = snapshot.time();
            run.ingestedAt = LocalDateTime.now();

            // 不作气象声明的轮次（CLEAR/UNKNOWN）没有可判要素：必需要素全缺席，
            // 强行进入规则引擎只会被校验层拒绝——这正是修复前 /health/ready 恒 503 的成因。
            // 这里显式走「有来源但不作声明」的降级，而不是把「没有数据」伪装成满分适飞。
            SfiEngine.SfiResult rule = requested.needsWeather()
                    ? sfiEngine.evaluate(snapshot)
                    : sfiEngine.abstain();
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

            remember(requested);
            checkAndAlert(run.runId, record, previous, rule, track2, fused, rule.level(), null);

            Map<String, Object> dashboard = buildDashboard();
            broadcastDashboard(run.runId);
            try {
                WeatherSnapshot submittedSnapshot = snapshot;
                List<ForecastHour> submittedForecast = List.copyOf(forecast);
                track2Executor.execute(() -> completeTrack2(run, record, submittedSnapshot,
                        submittedForecast, rule, previous));
            } catch (RejectedExecutionException rejected) {
                commits.failTrack2(run, track, "QUEUE_REJECTED", "轨2队列已满，本轮保留规则结果");
                commits.finishTrack2Job(run.runId, "FAILED", "QUEUE_REJECTED");
                dashboard = buildDashboard();
                broadcastDashboard(run.runId);
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
                    broadcastDashboard(run.runId);
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
                    broadcastDashboard(run.runId);
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
            broadcastDashboard(run.runId);
        }
    }

    private WeatherSnapshot convertSnapshot(Map<String, Object> generated) {
        return mapper.convertValue(generated.get("snapshot"), WeatherSnapshot.class);
    }

    private List<ForecastHour> convertForecast(Map<String, Object> generated) {
        return mapper.convertValue(generated.get("hourly"),
                mapper.getTypeFactory().constructCollectionType(List.class, ForecastHour.class));
    }

    /**
     * 一个每个气象量都为空、且来源明确标为 NONE 的快照。
     *
     * 这是 CLEAR / UNKNOWN 口径下的诚实表示：不是「零风速、零降水」，而是
     * 「本轮没有气象数据」。用 0 填充会让 SFI 引擎把「没取到」算成「天气很好」，
     * 从而给出一个偏乐观的等级——这正是必须避免的那类静默错误。
     */
    private WeatherSnapshot absentSnapshot() {
        return new WeatherSnapshot(
                null, "none", qw.lat(), qw.lon(),
                null, null, null, null, null, null, null, null, null, null, null,
                // 「不作气象声明」的轮次里连来源都没有，自然谈不上观测时刻。这里给
                // UNSPECIFIED 而不是 NOT_PROVIDED：后者是一句关于**某个来源**的陈述，
                // 而这一轮的 effectiveSource 是 none。该快照从不到达规则引擎
                // （CLEAR/UNKNOWN 分支走 sfiEngine.abstain()），所以它保持 fail-closed。
                WeatherSnapshot.TIME_BASIS_UNSPECIFIED);
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
        // 记录本轮采用的气象口径。以前这里存的是合成剧本名；现在每一轮都是真实
        // 来源，所以只在确实做了降级（用到公共源或气象不可用）时保留口径，正常轮次
        // 记 null，避免把「正常」写成某个看起来像剧本的值。
        e.scenario = run.degraded ? run.scenario : null;
        e.sfi = rule.sfi();
        e.rawSfi = rule.rawSfi();
        e.level = rule.level().name();
        e.hardBan = rule.hardBan();
        e.ruleVersion = rule.ruleVersion();
        e.lat = s.lat();
        e.lon = s.lon();
        e.conditionText = s.conditionText();
        // 实体字段是原始 double，容不下 null。缺席在库里记 NaN，语义是
        // 「这一轮没有该要素」，与「测到了 0」区分开——0 是有效的无风/无降水。
        // 先前直接拆箱会在不作气象声明的轮次抛 NPE，把整轮监测打成 MONITOR_FAILED。
        e.windSpeed = boxed(s.windSpeed());
        e.windGust = boxed(s.windGust());
        e.windDeg = s.windDeg();
        e.precipMmh = boxed(s.precipMmh());
        e.visibilityM = boxed(s.visibilityM());
        e.thunderProb = boxed(s.thunderProb());
        e.tempC = boxed(s.tempC());
        e.humidity = boxed(s.humidity());
        e.pressureHpa = boxed(s.pressureHpa());
        e.cloudCover = boxed(s.cloudCover());
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
        // 看哪一轮是**调用方自己的工作区口径**决定的：采集全机只发生一次（对同一个世界的
        // 测量），但 A 切到 clear 之后 B 的屏幕不该跟着换一套预报。取最新一轮正是这条
        // 泄漏路径 —— 两块屏都写着当前情景：clear，看不出是谁改了谁。
        Scenario scenario = applied();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("version", 1);
        out.put("serverTime", LocalDateTime.now().toString());
        out.put("configuredMode", monitor.mode());
        out.put("mode", monitor.mode()); // 前端过渡兼容
        out.put("regionId", regionId());
        out.put("region", qw.regionName());
        out.put("taskType", qw.taskType());

        Optional<MonitoringRunEntity> completed = runRepo.findFirstByRegionIdAndConfiguredModeAndScenarioAndStatusInOrderByIdDesc(
                regionId(), monitor.mode(), scenario.key(), List.of("RULE_READY", "COMPLETE"));
        Optional<MonitoringRunEntity> latestAttempt = runRepo.findFirstByRegionIdAndConfiguredModeAndScenarioOrderByIdDesc(
                regionId(), monitor.mode(), scenario.key());
        if (completed.isEmpty()) {
            out.put("runId", null);
            out.put("runSequence", 0);
            out.put("revision", 0);
            out.put("status", "WAITING");
            out.put("dataStatus", "NO_DATA");
            out.put("scenario", scenario.key());
            out.put("appliedScenario", scenario.key());
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
            out.put("scenario", scenario.key());
            out.put("appliedScenario", scenario.key());
            // 这一轮实际是在哪个口径下采的。正常与 appliedScenario 相同（取数就是按它筛的），
            // 但两个字段分开写：一个是我要看什么，另一个是这份数据是怎么来的。
            out.put("runScenario", run.scenario);
            out.put("obsTime", run.obsTime);
            // 观测时刻**怎么来的**，与观测时刻本身一起发。没有它，调用方看到
            // `obsTime: null` + `dataStatus: FRESH` 会读成一对自相矛盾的字段，
            // 而真相是「来源不提供观测时刻，新鲜度按取数时刻计」——一句必须说出口的话。
            out.put("obsTimeBasis", observationTimeBasis(run.snapshotJson));
            out.put("updatedAt", value(run.updatedAt));
            out.put("lastRunAt", value(run.updatedAt));
            out.put("dataStatus", freshness(run.obsTime, run.ingestedAt));
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
        // 库里用 NaN 表示「这一轮没有该要素」；出到接口必须还原成 null。
        // NaN 不是合法 JSON，直接发出去会让整个面板的解析失败——一个缺席的要素
        // 不该把整张页面打坏。
        snapshot.put("tempC", jsonly(e.tempC));
        snapshot.put("humidity", jsonly(e.humidity));
        snapshot.put("windSpeed", jsonly(e.windSpeed));
        snapshot.put("windGust", jsonly(e.windGust));
        snapshot.put("windDeg", e.windDeg);
        snapshot.put("precipMmh", jsonly(e.precipMmh));
        snapshot.put("visibilityM", jsonly(e.visibilityM));
        snapshot.put("pressureHpa", jsonly(e.pressureHpa));
        snapshot.put("cloudCover", jsonly(e.cloudCover));
        snapshot.put("thunderProb", jsonly(e.thunderProb));

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
                        h.precipMmh(), h.visibilityM(), 1010.0, 0.8, h.thunderProb(),
                        WeatherSnapshot.TIME_BASIS_OBSERVED);
                SfiEngine.SfiResult r = sfiEngine.evaluate(synthetic);
                result.add(Map.of("time", h.time(), "sfi", r.sfi(), "level", r.level().name(),
                        "levelLabel", r.level().label));
            } catch (Exception e) {
                log.warn("预报点无效 time={}: {}", h.time(), e.getMessage());
            }
        }
        return result;
    }

    /**
     * 观测时刻的基准，读自**已落盘的快照**（{@code monitoring_run.snapshot_json}）。
     *
     * <p>为什么读 JSON 而不再加一列：{@code snapshotJson} 本来就是整份 {@code WeatherSnapshot}
     * 的序列化结果，而 {@code timeBasis} 是它的一个分量 —— 加列意味着一次 Flyway 迁移，
     * 而迁移在服务器上跑过就回不去（M24 那条：回滚 jar 也修不好一条已记失败的迁移）。
     * 这里取不到就返回 {@code null}（这一列在老数据上确实没有），**不推断** ——
     * 「没有表态」与「表态了是 OBSERVED」是两句话。</p>
     */
    private String observationTimeBasis(String snapshotJson) {
        if (snapshotJson == null || snapshotJson.isBlank()) return null;
        try {
            JsonNode basis = mapper.readTree(snapshotJson).path("timeBasis");
            return basis.isTextual() && !basis.asText().isBlank() ? basis.asText() : null;
        } catch (Exception ignored) {
            return null;
        }
    }

    /**
     * 数据新鲜度。
     *
     * <p>{@code obsTime} 缺席时退回**取数时刻**（{@code ingestedAt}），而不是直接返回
     * {@code UNKNOWN}。理由是这三个状态说的不是一件事：{@code STALE} 是「我知道它旧了」，
     * {@code FRESH} 是「在我能量到的尺度上它是新的」，{@code UNKNOWN} 是「我量不到」。
     * 和风 v1 不提供观测时刻之后，若统一返回 {@code UNKNOWN}，{@code /api/health/ready}
     * 那条 {@code "FRESH".equals(dataStatus)} 的判据就永远为假 —— 服务会一直 503，
     * 而它其实每一轮都在正常取数。所以「按取数时刻量」是这里唯一既诚实又可用的一支，
     * 并且它的口径随 {@code obsTimeBasis} 一起发出，读的人知道这个年龄是从哪儿算起的。</p>
     */
    private String freshness(String obsTime, LocalDateTime ingestedAt) {
        OffsetDateTime at = parseInstant(obsTime);
        if (at == null && ingestedAt != null) {
            at = ingestedAt.atZone(ZoneId.systemDefault()).toOffsetDateTime();
        }
        if (at == null) return "UNKNOWN";
        try {
            long age = Duration.between(at, OffsetDateTime.now()).toMinutes();
            return age >= 0 && age <= Math.max(20, monitor.fixedDelayMs() / 30_000) ? "FRESH" : "STALE";
        } catch (Exception ignored) {
            return "UNKNOWN";
        }
    }

    private OffsetDateTime parseInstant(String text) {
        if (text == null || text.isBlank()) return null;
        try {
            return OffsetDateTime.parse(text);
        } catch (Exception ignored) {
            return null;
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

    /**
     * 可缺席的 Double → 实体的原始 double。缺席记 NaN 而非 0：
     * 0 是「测到了 0」（无风、无降水），NaN 才是「这一轮没这个要素」。
     */
    private double boxed(Double value) {
        return value == null ? Double.NaN : value;
    }

    /** 与 {@link #boxed} 反向：NaN 表示缺席，出接口时还原成 null（NaN 不是合法 JSON）。 */
    private Double jsonly(double value) {
        return Double.isNaN(value) ? null : value;
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
