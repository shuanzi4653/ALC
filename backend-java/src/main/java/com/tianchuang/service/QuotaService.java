package com.tianchuang.service;

import com.tianchuang.config.QuotaProperties;
import com.tianchuang.entity.LlmQuotaEntity;
import com.tianchuang.repository.LlmQuotaRepo;

import java.time.Clock;
import java.time.LocalDate;
import java.time.ZoneId;
import java.util.LinkedHashMap;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

@Service
public class QuotaService {

    private static final Logger log = LoggerFactory.getLogger(QuotaService.class);

    public static final String DIM_WORKSPACE = "workspace";
    public static final String DIM_IP = "ip";

    public static final String UNKNOWN_ADDRESS = "unknown";

    public record Verdict(boolean allowed, String dimension, long used, long limit) {
    }

    private final QuotaProperties props;
    private final LlmQuotaRepo repo;
    private final Clock clock;

    @Autowired
    public QuotaService(QuotaProperties props, LlmQuotaRepo repo) {
        this(props, repo, Clock.system(ZoneId.of(props.zone())));
    }

    public QuotaService(QuotaProperties props, LlmQuotaRepo repo, Clock clock) {
        this.props = props;
        this.repo = repo;
        this.clock = clock;
    }

    public Verdict charge(String workspace, String clientAddress) {
        String day = today();
        Integer wsLimit = props.workspacePerDay();
        String ws = identified(workspace) ? workspace : null;

        if (ws != null && bump(day, DIM_WORKSPACE, ws, wsLimit) == 0) {
            return new Verdict(false, DIM_WORKSPACE, usedOf(day, DIM_WORKSPACE, ws), wsLimit);
        }

        String ip = blank(clientAddress) ? UNKNOWN_ADDRESS : clientAddress;
        Integer ipLimit = props.ipPerDay();
        if (bump(day, DIM_IP, ip, ipLimit) == 0) {
            if (ws != null) {
                repo.decrement(bucket(day, DIM_WORKSPACE, ws));
            }
            return new Verdict(false, DIM_IP, usedOf(day, DIM_IP, ip), ipLimit);
        }
        return new Verdict(true, "", 0L, 0L);
    }

    public Map<String, Object> status(String workspace, String clientAddress) {
        String day = today();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("enabled", props.enabled());
        out.put("day", day);
        out.put("zone", props.zone());
        out.put("workspace", usage(day, DIM_WORKSPACE, identified(workspace) ? workspace : null,
                props.workspacePerDay()));
        out.put("ip", usage(day, DIM_IP, blank(clientAddress) ? UNKNOWN_ADDRESS : clientAddress,
                props.ipPerDay()));
        return out;
    }

    @Scheduled(cron = "${quota.cleanup-cron:0 45 3 * * *}")
    public void scheduledCleanup() {
        try {
            log.info("配额台账清理完成：{}", cleanup());
        } catch (Exception e) {
            log.error("配额台账清理失败（保留期外台账未回收）", e);
        }
    }

    public Map<String, Object> cleanup() {
        String cutoff = LocalDate.now(clock).minusDays(props.keepDays()).toString();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("cutoff", cutoff);
        out.put("removed", repo.deleteByDayLessThan(cutoff));
        return out;
    }

    String today() {
        return LocalDate.now(clock).toString();
    }

    public static boolean identified(String workspace) {
        return !blank(workspace);
    }

    private static boolean blank(String value) {
        return value == null || value.isBlank();
    }

    private int bump(String day, String dimension, String key, int limit) {
        String bucket = bucket(day, dimension, key);
        if (!repo.existsById(bucket)) {
            try {
                repo.saveAndFlush(new LlmQuotaEntity(bucket, day, dimension, key));
            } catch (DataIntegrityViolationException race) {
                log.debug("配额桶 {} 已被并发创建", bucket);
            }
        }
        return repo.incrementWithinLimit(bucket, limit);
    }

    private long usedOf(String day, String dimension, String key) {
        return repo.findById(bucket(day, dimension, key)).map(row -> (long) row.used).orElse(0L);
    }

    private Map<String, Object> usage(String day, String dimension, String key, int limit) {
        if (key == null) {
            return Map.of("present", false);
        }
        long used = usedOf(day, dimension, key);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("present", true);
        out.put("used", used);
        out.put("limit", (long) limit);
        out.put("remaining", Math.max(0L, limit - used));
        return out;
    }

    private static String bucket(String day, String dimension, String key) {
        return day + "|" + dimension + "|" + key;
    }
}
