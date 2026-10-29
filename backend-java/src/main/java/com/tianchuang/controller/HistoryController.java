package com.tianchuang.controller;

import java.time.LocalDateTime;
import java.time.format.DateTimeParseException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import com.tianchuang.config.HistoryProperties;
import com.tianchuang.entity.AlertEntity;
import com.tianchuang.entity.MonitoringRunEntity;
import com.tianchuang.entity.SfiRecordEntity;
import com.tianchuang.repository.AlertRepo;
import com.tianchuang.repository.MonitoringRunRepo;
import com.tianchuang.repository.SfiRecordRepo;

import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/history")
public class HistoryController {

    private final MonitoringRunRepo runRepo;
    private final SfiRecordRepo sfiRepo;
    private final AlertRepo alertRepo;
    private final HistoryProperties history;

    public HistoryController(MonitoringRunRepo runRepo, SfiRecordRepo sfiRepo,
                             AlertRepo alertRepo, HistoryProperties history) {
        this.runRepo = runRepo;
        this.sfiRepo = sfiRepo;
        this.alertRepo = alertRepo;
        this.history = history;
    }

    @GetMapping("/runs")
    public Map<String, Object> runs(@RequestParam(required = false) String regionId,
                                    @RequestParam(required = false) String since,
                                    @RequestParam(defaultValue = "0") int page,
                                    @RequestParam(defaultValue = "20") int size) {
        PageRequest request = pageRequest(page, size);
        LocalDateTime sinceTime = parseSince(since);

        Page<MonitoringRunEntity> result;
        if (regionId != null && !regionId.isBlank() && sinceTime != null) {
            result = runRepo.findByRegionIdAndStartedAtAfterOrderByIdDesc(regionId, sinceTime, request);
        } else if (regionId != null && !regionId.isBlank()) {
            result = runRepo.findByRegionIdOrderByIdDesc(regionId, request);
        } else if (sinceTime != null) {
            result = runRepo.findByStartedAtAfterOrderByIdDesc(sinceTime, request);
        } else {
            result = runRepo.findAllByOrderByIdDesc(request);
        }
        return pageBody(result);
    }

    @GetMapping("/sfi")
    public Map<String, Object> sfi(@RequestParam(required = false) String regionId,
                                   @RequestParam(defaultValue = "0") int page,
                                   @RequestParam(defaultValue = "20") int size) {
        PageRequest request = pageRequest(page, size);
        Page<SfiRecordEntity> result = (regionId == null || regionId.isBlank())
                ? sfiRepo.findAllByOrderByTsDesc(request)
                : sfiRepo.findByRegionIdOrderByTsDesc(regionId, request);
        return pageBody(result);
    }

    @GetMapping("/alerts")
    public Map<String, Object> alerts(@RequestParam(defaultValue = "0") int page,
                                      @RequestParam(defaultValue = "20") int size) {
        return pageBody(alertRepo.findAllByOrderByTsDesc(pageRequest(page, size)));
    }

    private PageRequest pageRequest(int page, int size) {
        if (page < 0) {
            throw new IllegalArgumentException("page 不能为负数");
        }
        if (size <= 0) {
            throw new IllegalArgumentException("size 必须为正数");
        }
        if (size > history.maxPageSize()) {
            throw new IllegalArgumentException("size 超过上限 " + history.maxPageSize());
        }
        return PageRequest.of(page, size);
    }

    private LocalDateTime parseSince(String since) {
        if (since == null || since.isBlank()) {
            return null;
        }
        try {
            return LocalDateTime.parse(since.trim());
        } catch (DateTimeParseException e) {
            throw new IllegalArgumentException("since 需为 ISO-8601 本地时间，例如 2026-09-11T00:00:00");
        }
    }

    private Map<String, Object> pageBody(Page<?> result) {
        Map<String, Object> body = new LinkedHashMap<>();
        List<?> items = result.getContent();
        body.put("items", items);
        body.put("total", result.getTotalElements());
        body.put("page", result.getNumber());
        body.put("size", result.getSize());
        body.put("totalPages", result.getTotalPages());
        body.put("hasNext", result.hasNext());
        return body;
    }
}
