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

/**
 * 轨1 推理留痕的写入与汇总。
 *
 * <p><b>三条纪律：</b></p>
 * <ol>
 *   <li><b>留痕失败绝不影响推理结果。</b>{@link #record} 全程吞异常并只记 warn。
 *       理由：留痕是给"事后看模型表现如何"用的，推理是给"这一轮能不能飞"用的。
 *       让前者把后者弄挂，等于为了记账把车开进沟里。反过来也一样 ——
 *       不能因为"写不进去"就假装这一轮没发生，所以失败必须留日志。</li>
 *   <li><b>三态不许压成两态。</b>一致 / 不一致 / <b>不可比</b>。第三态在这里独立成
 *       {@code notComparable} 并<b>不进</b>一致率的分母 —— 把它算成"不一致"会让
 *       模型没参与的那几轮看起来像"模型判错了"，而两者是完全不同的事。</li>
 *   <li><b>分子分母都返回。</b>只给一个 0.82 的话，读的人无法判断它是"11 次里 9 次"
 *       还是"1100 次里 902 次"。凡是要进报告的比例，都同时给 n。</li>
 * </ol>
 */
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

    // ------------------------------------------------------------------ 写

    /**
     * 把一次推理写进留痕表。<b>不抛异常</b>。
     *
     * @param request  请求体（含 {@code snapshot}），用于算输入指纹
     * @param response Python 返回体（{@link Map}），取档位 / 置信度 / top3 等
     */
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
            // available=false 时 Python 不返回档位。这里填 'UNAVAILABLE' 只为满足 NOT NULL，
            // 统计侧一律 where available = true，所以它不会混进四档分布。
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

            // 一致与否只在两边都真有档位时才成立。任一侧为空 ⇒ null（不可比），不是 false。
            if (e.ruleLevel != null && !e.ruleLevel.isBlank() && available) {
                e.agree = e.ruleLevel.equalsIgnoreCase(e.level);
            } else {
                e.agree = null;
            }

            e.inputsSha256 = fingerprint(request);
            repo.save(e);
        } catch (Exception ex) {
            // 留痕是旁路。它的失败要在日志里可见，但绝不能冒泡到推理调用方。
            log.warn("轨1 留痕写入失败（不影响本轮推理结果）：{}", ex.toString());
        }
    }

    // ------------------------------------------------------------------ 读

    /**
     * 成效页三列需要的全部数字。窗口按小时给。
     *
     * <p>表不存在时返回 {@code available=false} 而不是抛异常 —— 与 Python 侧
     * "模型缺席是正常状态"同一条规矩：把"这一版还没建表"报成 500，
     * 会让前端把它读成"后端挂了"。</p>
     */
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
            // 分母是 comparable，**不含 notComparable**。这一行的注释就是它的说明书。
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
                // 「窗口里一条都没有」与「有记录但全是 0」必须长得不一样。
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

    // ------------------------------------------------------------- 小工具

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

    /** 输入指纹：规范化（键排序）后的请求体 SHA-256。**不存原文**，只存指纹。 */
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

    /** 比例统一 4 位小数；分母为 0 时返回 {@code null} 而<b>不是</b> 0 —— 「没有」≠「是 0」。 */
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
