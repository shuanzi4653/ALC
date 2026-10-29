package com.tianchuang.support;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.tianchuang.entity.LlmQuotaEntity;
import com.tianchuang.repository.LlmQuotaRepo;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 把一张 {@code Map} 当成 {@code llm_quota} 表用。
 *
 * <p><b>为什么抽出来共享，而不是每个测试各写一份：</b>配额的行为由「条件自增」
 * 那一条 SQL 定义（{@code ... WHERE used < limit}）。如果服务测试和过滤器测试各自
 * 仿一份，两份会慢慢长得不一样 —— 于是某天过滤器那条判据其实量的是"假表"的语义，
 * 而两条判据都是绿的（M84 同型：对照侧与被测实现没枚举同一个集合）。放一处，
 * 「假表的语义」就只有一个副本，改错了会同时反映到两个测试上。</p>
 *
 * <p>这里照抄的正是 {@link LlmQuotaRepo#incrementWithinLimit} 的判定：
 * <b>先比较、再加</b>，加不上就返回 0。写成"先加再比较"会让上限多放行一次，
 * 而单次边界用例刚好量不到（第 limit+1 次才拒 ⇒ 实际成了 limit+1）。</p>
 */
public final class QuotaTestSupport {

    private QuotaTestSupport() {
    }

    /** 建一个由 {@code rows} 支撑的假仓库；{@code rows} 的键是 bucketKey。 */
    public static LlmQuotaRepo inMemoryRepo(Map<String, LlmQuotaEntity> rows) {
        LlmQuotaRepo repo = mock(LlmQuotaRepo.class);

        when(repo.existsById(anyString()))
                .thenAnswer(call -> rows.containsKey(call.getArgument(0, String.class)));

        when(repo.findById(anyString()))
                .thenAnswer(call -> Optional.ofNullable(rows.get(call.getArgument(0, String.class))));

        when(repo.saveAndFlush(any())).thenAnswer(call -> {
            LlmQuotaEntity row = call.getArgument(0);
            rows.put(row.bucketKey, row);
            return row;
        });

        when(repo.incrementWithinLimit(anyString(), anyInt())).thenAnswer(call -> {
            LlmQuotaEntity row = rows.get(call.getArgument(0, String.class));
            int limit = call.getArgument(1, Integer.class);
            if (row == null || row.used >= limit) {
                return 0;
            }
            row.used += 1;
            return 1;
        });

        when(repo.decrement(anyString())).thenAnswer(call -> {
            LlmQuotaEntity row = rows.get(call.getArgument(0, String.class));
            if (row == null || row.used <= 0) {
                return 0;
            }
            row.used -= 1;
            return 1;
        });

        // 清理也要真删：让它默认返回 0（Mockito 对 int 的默认值）会让"清理只删过期日"
        // 这条判据永远成立 —— 一条恒真的判据等于没有判据。
        when(repo.deleteByDayLessThan(anyString())).thenAnswer(call -> {
            String cutoff = call.getArgument(0, String.class);
            List<String> expired = rows.values().stream()
                    .filter(row -> row.quotaDay.compareTo(cutoff) < 0)
                    .map(row -> row.bucketKey)
                    .toList();
            expired.forEach(rows::remove);
            return expired.size();
        });

        return repo;
    }
}
