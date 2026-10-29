package com.tianchuang.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.tianchuang.entity.MlInferenceEntity;
import com.tianchuang.repository.MlInferenceRepo;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@Service
public class MlInferenceRecorder {

    private static final Logger log = LoggerFactory.getLogger(MlInferenceRecorder.class);
    private static final List<String> LEVELS = List.of("FIT", "CAUTION", "DANGER", "BAN");

    private final MlInferenceRepo repo;
    private final ObjectMapper canon = new ObjectMapper()
            .configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);

    public MlInferenceRecorder(MlInferenceRepo repo) {
        this.repo = repo;
    }

    public void record(Map<String, Object> request, Object response) {
        try {
            Map<String, Object> res = asMap(response);
            if (res == null) {
                log.warn("轨1 留痕跳过：响应体不是 JSON 对象");
                return;
            }
            MlInferenceEntity e = new MlInferenceEntity();
            boolean available = Boolean.TRUE.equals(res.get("available"));
            e.available = available;
            e.reason = available ? null : str(res.get("status"), 48);
            e.level = available ? str(res.get("level"), 16) : "UNAVAILABLE";
            if (e.level == null || e.level.isBlank()) {
                e.level = "UNAVAILABLE";
                e.available = false;
            }

            e.confidence = dec(res.get("confidence"));
            e.margin = dec(res.get("margin"));
            e.lowConfidence = Boolean.TRUE.equals(res.get("lowConfidence"));
            Map<String, Object> degraded = asMap(res.get("degraded"));
            e.degraded = degraded != null && Boolean.TRUE.equals(degraded.get("flag"));
            e.missingCount = intOf(res.get("missingFeatures"));
            e.top3 = jsonOrNull(res.get("top3"));
            e.modelVersion = str(res.get("modelVersion"), 32);
            if (e.modelVersion == null) e.modelVersion = "unknown";
            e.labelsVersion = str(res.get("labelsVersion"), 32);

            e.workspaceId = com.tianchuang.config.WorkspaceContext.current();
            if (e.workspaceId != null && e.workspaceId.isBlank()) e.workspaceId = null;

            e.sessionId = str(res.get("sessionId"), 80);
            if (e.sessionId == null) e.sessionId = str(request == null ? null : request.get("sessionId"), 80);
            e.sampleKey = str(res.get("sampleKey"), 64);
            if (e.sampleKey == null) e.sampleKey = str(request == null ? null : request.get("sampleKey"), 64);
            e.ruleLevel = str(res.get("ruleLevel"), 16);
            if (e.ruleLevel == null) e.ruleLevel = str(request == null ? null : request.get("ruleLevel"), 16);

            if (e.ruleLevel != null && !e.ruleLevel.isBlank() && available) {
                e.agree = e.ruleLevel.equalsIgnoreCase(e.level);
            } else {
                e.agree = null;
            }

            e.inputsSha256 = fingerprint(request);
            repo.save(e);
        } catch (Exception ex) {
            log.warn("轨1 留痕写入失败（不影响本轮推理结果）：{}", ex.toString());
        }
    }

    public Map<String, Object> summary(int windowHours) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("windowHours", windowHours);
        try {
            LocalDateTime since = LocalDateTime.now().minusHours(Math.max(1, windowHours));
            long total = repo.countByCreatedAtGreaterThanEqual(since);
            long available = repo.countByAvailableTrueAndCreatedAtGreaterThanEqual(since);

            Map<String, Long> levels = new LinkedHashMap<>();
            for (String lv : LEVELS) levels.put(lv, 0L);
            for (Object[] row : repo.countByLevelSince(since)) {
                String lv = row[0] == null ? null : String.valueOf(row[0]);
                long n = row[1] == null ? 0L : ((Number) row[1]).longValue();
                if (lv != null && levels.containsKey(lv)) levels.put(lv, levels.get(lv) + n);
            }
            Map<String, Object> share = new LinkedHashMap<>();
            for (Map.Entry<String, Long> en : levels.entrySet()) {
                share.put(en.getKey(), ratio(en.getValue(), available));
            }

            long agree = 0, disagree = 0, notComparable = 0;
            for (Object[] row : repo.countByAgreeSince(since)) {
                long n = row[1] == null ? 0L : ((Number) row[1]).longValue();
                Object flag = row[0];
                if (flag == null) notComparable += n;
                else if (Boolean.TRUE.equals(flag)) agree += n;
                else disagree += n;
            }
            long comparable = agree + disagree;

            Map<String, Object> agreement = new LinkedHashMap<>();
            agreement.put("agree", agree);
            agreement.put("disagree", disagree);
            agreement.put("notComparable", notComparable);
            agreement.put("comparable", comparable);
            agreement.put("rate", ratio(agree, comparable));
            agreement.put("note", "一致率分母为「可比轮次」（模型与规则都有档位），不含模型未参与的轮次");

            List<MlInferenceEntity> latest = repo
                    .findByCreatedAtGreaterThanEqualOrderByCreatedAtDesc(since);

            out.put("available", true);
            out.put("total", total);
            out.put("modelAvailable", available);
            out.put("modelUnavailable", total - available);
            out.put("availability", ratio(available, total));
            out.put("levels", levels);
            out.put("levelShare", share);
            out.put("agreement", agreement);
            out.put("latest", latest.isEmpty() ? null : brief(latest.get(0)));
            out.put("hasAny", total > 0);
            if (total == 0) {
                out.put("empty", true);
                out.put("note", "窗口内没有留痕记录 —— 不是「一致率 0」，是「还没跑过」");
            }
            return out;
        } catch (Exception ex) {
            log.warn("轨1 成效汇总不可用：{}", ex.toString());
            out.put("available", false);
            out.put("reason", "QUERY_FAILED");
            out.put("detail", ex.getClass().getSimpleName());
            return out;
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> asMap(Object o) {
        return (o instanceof Map) ? (Map<String, Object>) o : null;
    }

    private String str(Object o, int max) {
        if (o == null) return null;
        String s = String.valueOf(o).trim();
        if (s.isEmpty() || "null".equals(s)) return null;
        return s.length() > max ? s.substring(0, max) : s;
    }

    private BigDecimal dec(Object o) {
        if (o instanceof Number n) {
            return BigDecimal.valueOf(n.doubleValue()).setScale(4, RoundingMode.HALF_UP);
        }
        return null;
    }

    private int intOf(Object o) {
        if (o instanceof List<?> list) return list.size();
        if (o instanceof Number n) return n.intValue();
        return 0;
    }

    private String jsonOrNull(Object o) {
        if (o == null) return null;
        try {
            return canon.writeValueAsString(o);
        } catch (Exception ex) {
            return null;
        }
    }

    private String fingerprint(Map<String, Object> request) {
        if (request == null) return null;
        try {
            Object snapshot = request.get("snapshot");
            String text = canon.writeValueAsString(snapshot == null ? request : snapshot);
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest(text.getBytes(StandardCharsets.UTF_8));
            StringBuilder sb = new StringBuilder(64);
            for (byte b : d) sb.append(String.format("%02x", b));
            return sb.toString();
        } catch (Exception ex) {
            return null;
        }
    }

    private BigDecimal ratio(long part, long whole) {
        if (whole <= 0) return null;
        return BigDecimal.valueOf(part).divide(BigDecimal.valueOf(whole), 4, RoundingMode.HALF_UP);
    }

    private Map<String, Object> brief(MlInferenceEntity e) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("level", e.level);
        m.put("confidence", e.confidence);
        m.put("available", e.available);
        m.put("agree", e.agree);
        m.put("ruleLevel", e.ruleLevel);
        m.put("modelVersion", e.modelVersion);
        m.put("createdAt", e.createdAt == null ? null : e.createdAt.toString());
        return m;
    }
}
