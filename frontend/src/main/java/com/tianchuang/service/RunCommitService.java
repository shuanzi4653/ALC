package com.tianchuang.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.entity.MonitoringRunEntity;
import com.tianchuang.entity.SfiRecordEntity;
import com.tianchuang.entity.Track2JobEntity;
import com.tianchuang.entity.TrackResultEntity;
import com.tianchuang.model.ForecastHour;
import com.tianchuang.model.WeatherSnapshot;
import com.tianchuang.repository.MonitoringRunRepo;
import com.tianchuang.repository.SfiRecordRepo;
import com.tianchuang.repository.Track2JobRepo;
import com.tianchuang.repository.TrackResultRepo;
import java.time.LocalDateTime;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 把一轮运行及其规则/双轨结果作为一个数据库事务提交。 */
@Service
public class RunCommitService {
    private final MonitoringRunRepo runRepo;
    private final SfiRecordRepo sfiRepo;
    private final TrackResultRepo trackRepo;
    private final Track2JobRepo jobRepo;
    private final ObjectMapper mapper;

    public RunCommitService(MonitoringRunRepo runRepo, SfiRecordRepo sfiRepo,
                            TrackResultRepo trackRepo, Track2JobRepo jobRepo,
                            ObjectMapper mapper) {
        this.runRepo = runRepo;
        this.sfiRepo = sfiRepo;
        this.trackRepo = trackRepo;
        this.jobRepo = jobRepo;
        this.mapper = mapper;
    }

    public MonitoringRunEntity start(MonitoringRunEntity run) {
        return runRepo.save(run);
    }

    @Transactional
    public void completeWithTrack2Job(MonitoringRunEntity run, WeatherSnapshot snapshot,
                                      List<ForecastHour> forecast, SfiRecordEntity sfi,
                                      TrackResultEntity track, LocalDateTime dueAt) {
        try {
            run.snapshotJson = mapper.writeValueAsString(snapshot);
            run.forecastJson = mapper.writeValueAsString(forecast);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("运行快照序列化失败", e);
        }
        sfiRepo.save(sfi);
        trackRepo.save(track);
        run.status = "RULE_READY";
        run.updatedAt = LocalDateTime.now();
        runRepo.save(run);
        createTrack2Job(run.runId, run.regionId, dueAt);
    }

    @Transactional
    public void completeTrack2(MonitoringRunEntity run, TrackResultEntity track) {
        track.revision = 2;
        track.status = "COMPLETE";
        trackRepo.save(track);
        run.revision = 2;
        run.status = "COMPLETE";
        run.updatedAt = LocalDateTime.now();
        runRepo.save(run);
    }

    @Transactional
    public void failTrack2(MonitoringRunEntity run, TrackResultEntity track, String status, String detail) {
        track.revision = 2;
        track.status = status;
        track.track2Source = status.toLowerCase();
        track.track2Advice = detail;
        trackRepo.save(track);
        run.revision = 2;
        run.status = "COMPLETE";
        run.updatedAt = LocalDateTime.now();
        runRepo.save(run);
    }

    @Transactional
    public void fail(MonitoringRunEntity run, String errorCode, String message) {
        run.status = "FAILED";
        run.errorCode = errorCode;
        run.errorMessage = message == null ? "运行失败" : message.substring(0, Math.min(500, message.length()));
        run.updatedAt = LocalDateTime.now();
        runRepo.save(run);
    }

    // ---------------- 轨2任务持久化（C01） ----------------

    /**
     * 提交轨2任务记录（幂等）：jobKey 唯一，重复提交不会产生重复任务。
     * 任务先落库，随后才交给有界 executor 执行；JVM 崩溃时任务仍可在下次启动被收敛。
     */
    @Transactional
    public Track2JobEntity startTrack2Job(String runId, String regionId, LocalDateTime dueAt) {
        String key = jobKey(runId);
        Track2JobEntity existing = jobRepo.findFirstByJobKey(key).orElse(null);
        if (existing != null) {
            return existing;
        }
        return createTrack2Job(runId, regionId, dueAt);
    }

    private Track2JobEntity createTrack2Job(String runId, String regionId, LocalDateTime dueAt) {
        Track2JobEntity job = new Track2JobEntity();
        job.jobKey = jobKey(runId);
        job.runId = runId;
        job.regionId = regionId;
        job.jobKind = "TRACK2";
        job.status = "PENDING";
        job.attempts = 0;
        job.dueAt = dueAt;
        job.createdAt = LocalDateTime.now();
        job.updatedAt = job.createdAt;
        return jobRepo.save(job);
    }

    /** 单 worker 原子领取；非 PENDING 或已过期任务不再执行。 */
    @Transactional
    public Track2JobEntity claimTrack2Job(String runId) {
        Track2JobEntity job = jobRepo.findFirstByJobKey(jobKey(runId)).orElse(null);
        if (job == null || !"PENDING".equals(job.status)) return null;
        if (job.dueAt == null || !job.dueAt.isAfter(LocalDateTime.now())) return job;
        job.status = "RUNNING";
        job.attempts += 1;
        job.updatedAt = LocalDateTime.now();
        return jobRepo.save(job);
    }

    /** 任务收敛为终态；旧轮结果不得据此改写当前运行指针（由调用方按 runId 校验）。 */
    @Transactional
    public void finishTrack2Job(String runId, String status, String errorCode) {
        jobRepo.findFirstByJobKey(jobKey(runId)).ifPresent(job -> {
            job.status = status;
            job.errorCode = errorCode;
            job.updatedAt = LocalDateTime.now();
            jobRepo.save(job);
        });
    }

    /** 启动恢复：把上次进程退出时仍未收敛的任务标记为过期失败。 */
    @Transactional
    public int expireUnfinishedJobs(String errorCode) {
        List<Track2JobEntity> unfinished = jobRepo.findByStatusIn(List.of("PENDING", "RUNNING"));
        LocalDateTime now = LocalDateTime.now();
        for (Track2JobEntity job : unfinished) {
            job.status = "FAILED";
            job.errorCode = errorCode;
            job.updatedAt = now;
            jobRepo.save(job);
            trackRepo.findFirstByRunIdOrderByRevisionDesc(job.runId).ifPresent(track -> {
                track.revision = 2;
                track.status = "UNAVAILABLE";
                track.track2Source = "unavailable";
                track.track2Advice = "服务重启导致轨2任务中断，本轮保留规则结果";
                trackRepo.save(track);
            });
            runRepo.findByRunId(job.runId).ifPresent(run -> {
                if ("RULE_READY".equals(run.status)) {
                    run.revision = 2;
                    run.status = "COMPLETE";
                    run.updatedAt = now;
                    runRepo.save(run);
                }
            });
        }
        return unfinished.size();
    }

    private String jobKey(String runId) {
        return runId + ":TRACK2";
    }
}
