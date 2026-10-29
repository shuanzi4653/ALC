package com.tianchuang.config;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.entity.LlmQuotaEntity;
import com.tianchuang.repository.LlmQuotaRepo;
import com.tianchuang.service.QuotaService;
import com.tianchuang.support.QuotaTestSupport;

import jakarta.servlet.FilterChain;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneId;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

/**
 * 配额闸门的行为判据。每一条都走<b>真实的</b> {@link WorkspaceFilter} → {@link QuotaFilter}
 * 两跳，而不是直接调 {@code QuotaFilter} —— 顺序是这个功能的一部分：配额按工作区分格，
 * 而工作区是前一个过滤器绑到线程上的；直接把工作区手动 set 进去，等于把"顺序对不对"
 * 这件事从判据里拿掉了。
 */
class QuotaFilterTest {

    private static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");
    private static final Instant NOW = Instant.parse("2026-10-15T02:00:00Z");

    private static final String WS_A = "ws-aaaaaa";
    private static final String WS_B = "ws-bbbbbb";

    private Map<String, LlmQuotaEntity> rows;
    private QuotaService quota;
    private QuotaFilter filter;

    @AfterEach
    void tearDown() {
        WorkspaceContext.clear();
    }

    private void given(int workspacePerDay, int ipPerDay) {
        rows = new HashMap<>();
        LlmQuotaRepo repo = QuotaTestSupport.inMemoryRepo(rows);
        QuotaProperties props = new QuotaProperties(
                true, workspacePerDay, ipPerDay, null, "Asia/Shanghai", 7, null);
        quota = new QuotaService(props, repo, Clock.fixed(NOW, ZONE));
        filter = new QuotaFilter(props, quota, new ObjectMapper());
    }

    private record Outcome(boolean reached, int status, String contentType, String setCookie, String body) {
    }

    /** 走两跳过滤器；{@code reached=true} 表示请求真的走到了控制器（被放行）。 */
    private Outcome call(String uri, String... headers) throws Exception {
        return callWith("POST", uri, headers);
    }

    private Outcome callWith(String method, String uri, String... headers) throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest(method, uri);
        for (int i = 0; i + 1 < headers.length; i += 2) {
            request.addHeader(headers[i], headers[i + 1]);
        }
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicBoolean reached = new AtomicBoolean(false);
        FilterChain tail = (req, res) -> reached.set(true);

        new WorkspaceFilter().doFilter(request, response,
                (req, res) -> filter.doFilter(req, res, tail));

        return new Outcome(reached.get(), response.getStatus(), response.getContentType(),
                response.getHeader("Set-Cookie"), response.getContentAsString());
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> dimension(Map<String, Object> status, String name) {
        return (Map<String, Object>) status.get(name);
    }

    /**
     * 覆盖完全：**每一个能花钱或能改全机状态的写端点都要计费**。
     *
     * <p>2026-10-16 之前这份名单只有三条，漏掉的是 {@code /api/decisions/explain} ——
     * 与 {@code /api/traffic/explain} 并列的**第二条大模型入口**。漏掉它不报任何错：
     * 配额对它不生效，而"配额生效"的判据在它身上照样全绿。这条用例逐个端点问一遍，
     * 所以名单再被人改小一次就会红在这里。</p>
     *
     * <p>为什么不是断言"名单等于某个字面量"：那样的判据在**新增**一个计费端点时也会红，
     * 于是下一个人会去改判据而不是想清楚新端点该不该计费。这里钉的是行为（计费）而不是
     * 字面量。</p>
     */
    @Test
    void everyCostBearingWriteEndpointIsCharged() throws Exception {
        for (String uri : List.of(
                "/api/agent/ask",
                "/api/traffic/explain",
                "/api/decisions/explain",
                "/api/monitor/run-now",
                "/api/scenario/switch",
                "/api/traffic/weather/mode")) {
            given(5, 600);

            Outcome outcome = call(uri, "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4");

            assertThat(outcome.reached()).as("%s 应被放行（未超限）", uri).isTrue();
            assertThat(dimension(quota.status(WS_A, "1.2.3.4"), "workspace"))
                    .as("%s 必须计入工作区配额", uri).containsEntry("used", 1L);
        }
    }

    /**
     * 读与写必须分开：同一个路径的 GET 不计费，POST 计费。
     *
     * <p>{@code /api/traffic/weather/mode} 是一个路径两种用法 —— 运行台每次打开都 GET 它
     * 一次（读当前通道），只有操作员真的拨开关才 POST。路径级匹配会让"翻页"这件事
     * 消耗额度，于是一个纯演示的下午能把 120 格用掉大半，而"额度用完了"这句话会出现在
     * **什么也没干**的人面前。</p>
     *
     * <p>两个方向都钉：GET 之后计数必须仍是 0（否则就是把读也算了），POST 之后的第二次
     * POST 必须 429（否则就是把写也算漏了）。</p>
     */
    @Test
    void readingAChargedPathIsFreeButWritingItIsNot() throws Exception {
        given(1, 600);

        Outcome read = callWith("GET", "/api/traffic/weather/mode",
                "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4");
        assertThat(read.reached()).isTrue();
        assertThat(dimension(quota.status(WS_A, "1.2.3.4"), "workspace"))
                .as("读通道状态不得消耗额度").containsEntry("used", 0L);

        Outcome write = callWith("POST", "/api/traffic/weather/mode",
                "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4");
        assertThat(write.reached()).isTrue();
        assertThat(dimension(quota.status(WS_A, "1.2.3.4"), "workspace"))
                .as("改全机通道必须计费").containsEntry("used", 1L);

        Outcome again = callWith("POST", "/api/traffic/weather/mode",
                "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4");
        assertThat(again.status()).isEqualTo(429);
    }

    /**
     * 反向判据：<b>非计费路径一次都不该记</b>。
     *
     * <p>缺了这条，一个"所有请求都计数"的实现会让上面几条全绿 —— 但前端构建期每 2–3 秒
     * 一次的 {@code /api/traffic/session} 会在用户什么都没做的时候就把额度用光，
     * 症状是"构建到一半开始 429"，看上去像后端挂了。</p>
     */
    @Test
    void nonQuotaPathPassesThroughWithoutCharging() throws Exception {
        given(1, 600);

        Outcome outcome = call("/api/traffic/session", "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4");

        assertThat(outcome.reached()).isTrue();
        assertThat(outcome.status()).isEqualTo(200);
        assertThat(dimension(quota.status(WS_A, "1.2.3.4"), "workspace"))
                .as("轮询读接口不得计入配额").containsEntry("used", 0L);
    }

    @Test
    void quotaPathWithinLimitReachesController() throws Exception {
        given(2, 600);

        Outcome outcome = call("/api/agent/ask", "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4");

        assertThat(outcome.reached()).isTrue();
        assertThat(outcome.status()).isEqualTo(200);
        assertThat(dimension(quota.status(WS_A, "1.2.3.4"), "workspace")).containsEntry("used", 1L);
    }

    @Test
    void exhaustedQuotaReturns429AndNeverReachesController() throws Exception {
        given(1, 600);
        call("/api/agent/ask", "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4");

        Outcome outcome = call("/api/agent/ask", "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4");

        assertThat(outcome.reached()).as("闸门必须在控制器之前拦住它").isFalse();
        assertThat(outcome.status()).isEqualTo(429);
        assertThat(outcome.contentType()).startsWith("application/json");
        assertThat(outcome.body()).contains("QUOTA_EXCEEDED").contains("workspace");
        assertThat(outcome.setCookie())
                .as("429 只表达额度用完了，不得顺带改变客户端身份").isNull();
    }

    /** 一个工作区的配额用光，不该影响另一个 —— 与「两个用户互不关联」同一口径。 */
    @Test
    void exhaustedQuotaDoesNotAffectAnotherWorkspace() throws Exception {
        given(1, 600);
        call("/api/agent/ask", "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4");
        assertThat(call("/api/agent/ask", "X-ALC-Workspace", WS_A, "X-Real-IP", "1.2.3.4").status())
                .isEqualTo(429);

        Outcome other = call("/api/agent/ask", "X-ALC-Workspace", WS_B, "X-Real-IP", "1.2.3.4");

        assertThat(other.reached()).isTrue();
        assertThat(other.status()).isEqualTo(200);
    }

    /**
     * 没有 {@code X-Real-IP} 时只能读 {@code X-Forwarded-For}，此时<b>必须取最后一跳</b>。
     *
     * <p>nginx 的 {@code $proxy_add_x_forwarded_for} 把调用方自己发的前缀放在最左边，
     * 所以取第一段等于把 IP 配额交给调用方决定：每换一个伪造前缀就换一格新配额，
     * 而"配额生效"这条判据在单客户端测试下照样全绿。这条用例就是专门来红它的。</p>
     */
    @Test
    void forwardedForIsKeyedOnTheLastHopNotTheSpoofablePrefix() throws Exception {
        given(600, 1);

        Outcome first = call("/api/agent/ask", "X-ALC-Workspace", WS_A,
                "X-Forwarded-For", "9.9.9.9, 8.8.8.8");
        assertThat(first.status()).isEqualTo(200);

        Outcome rotatedPrefix = call("/api/agent/ask", "X-ALC-Workspace", WS_B,
                "X-Forwarded-For", "7.7.7.7, 8.8.8.8");
        assertThat(rotatedPrefix.status())
                .as("换掉可伪造的前缀不该换到一格新配额").isEqualTo(429);

        Outcome realLastHopChanged = call("/api/agent/ask", "X-ALC-Workspace", WS_B,
                "X-Forwarded-For", "8.8.8.8, 9.9.9.9");
        assertThat(realLastHopChanged.status())
                .as("最后一跳真的换了，才该是新的一格").isEqualTo(200);
    }

    /** 地址取值的信任顺序：不可伪造的头优先，可伪造的头只能读最后一跳。 */
    @Test
    void clientAddressPrefersTheNonSpoofableHeader() {
        MockHttpServletRequest both = new MockHttpServletRequest();
        both.addHeader("X-Real-IP", "1.1.1.1");
        both.addHeader("X-Forwarded-For", "9.9.9.9, 8.8.8.8");
        assertThat(QuotaFilter.clientAddress(both)).isEqualTo("1.1.1.1");

        MockHttpServletRequest onlyForwarded = new MockHttpServletRequest();
        onlyForwarded.addHeader("X-Forwarded-For", "9.9.9.9, 8.8.8.8");
        assertThat(QuotaFilter.clientAddress(onlyForwarded)).isEqualTo("8.8.8.8");

        MockHttpServletRequest bare = new MockHttpServletRequest();
        assertThat(QuotaFilter.clientAddress(bare)).isEqualTo("127.0.0.1");
    }
}
