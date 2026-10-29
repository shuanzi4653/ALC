package com.tianchuang.controller;

import com.tianchuang.service.MlInferenceRecorder;
import com.tianchuang.service.PythonClient;
import com.tianchuang.service.Track1Service;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.stream.Collectors;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Local facade; no arbitrary URL proxy and no external publication. */
@RestController
@RequestMapping("/api")
public class DecisionController {
    private final PythonClient python;
    private final MlInferenceRecorder mlRecorder;
    private final Track1Service track1;
    public DecisionController(PythonClient python, MlInferenceRecorder mlRecorder, Track1Service track1) {
        this.python = python;
        this.mlRecorder = mlRecorder;
        this.track1 = track1;
    }
    @GetMapping("/traffic/{resource:network|session|weather|operations|journal}")
    public ResponseEntity<?> traffic(@PathVariable String resource, @RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue())).collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/" + resource + "?" + query, null);
    }
    @PostMapping("/traffic/{resource:command|explain}")
    public ResponseEntity<?> trafficAction(@PathVariable String resource, @RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/traffic/" + resource, body);
    }
    // 运行日志的三条**写**入口（0.9.26（Beta） 第十轮起）：导出留痕、四态处置回执、
    // 一键处置动作。它们与 `/traffic/operations`（读，走上面 `{resource}` 白名单）
    // 路径**深度不同**，多一段，所以同样塞不进单段白名单 —— 与气象通道那次是同一个坑，
    // 注释留在同一处：少了这几行，前端 POST 会落到 Spring 默认错误响应，界面上只表现为
    // "点了没反应"，而 Python 侧的路由本身完全正常（`_audit_gateway_routes.py` 就是
    // 为了抓这一类而存在的）。
    //
    // `dispose` 是**第十一轮补上的第三个取值**，而它正是这条注释预警过的情形：
    // 第十轮新增一键处置前端时写了 `POST /api/traffic/operations/dispose`
    // （`OperationsConsole.vue` 的 `dispose()`），Python 也确有这条路由
    // （`main.py:342`），中间这一腿却没人补 —— 两端各自都"对"，缺的是中间那段。
    // 抓它的仍然是那条**跨层静态审计**：任何一端的单测都看不见它（同 M19）。
    // 三个取值都写明，不写成通配 `{action}`：通配会让这条审计失去对象，
    // 于是下一条新路径再漏时，审计还是绿的。
    @PostMapping("/traffic/operations/{action:note|disposal|dispose}")
    public ResponseEntity<?> operationsWrite(@PathVariable String action, @RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/traffic/operations/" + action, body);
    }
    // 气象通道控制器（实测 / 虚拟）。路径比其他 traffic 资源多一段，所以不能塞进
    // 上面 `{resource}` 的单个路径段白名单里 —— 这一点曾经漏掉，导致
    // GET/POST /api/traffic/weather/mode 谁都不匹配，落到 Spring 默认错误响应，
    // 前端只看到「切换中…」闪一下就没了。两个方法都要显式声明：
    // GET 读控制器状态（含实测源当前是否可用），POST 才是真正的切换。
    @GetMapping("/traffic/weather/mode")
    public ResponseEntity<?> weatherModeStatus() throws Exception {
        return python.decisionRequest("/traffic/weather/mode", null);
    }
    @PostMapping("/traffic/weather/mode")
    public ResponseEntity<?> weatherModeSet(@RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/traffic/weather/mode", body);
    }
    // 两条**免费补充气象通道**（0.9.35（Beta） 补上）：AWC 机场实测报文、Open-Meteo 双模型差值。
    //
    // 与 `weather/mode` 同一个坑、同一处说明：它们的路径比 `{resource}` 白名单**多一段**，
    // 塞不进去，必须显式声明。少了这两行，前端点了按钮只会看到"取数中…"闪一下，
    // 而 Python 侧的路由本身完全正常 —— 这是**第四次**同一形状的缺失
    // （前三次：`weather/mode`、`operations/dispose`、`radar/tiles`）。
    //
    // 三条纪律写在签名上，而不是只写在注释里：
    //   ① 只读（GET）—— 它们不改任何状态，故**不计配额**（`QuotaFilter` 只拦非安全方法，
    //      见 `ISS-0.9.34-02`：让"翻页看一眼"消耗额度，正常演示会自己挡住自己）；
    //   ② **不进主链路** —— 运行台每轮加载都要抓天气、目标 ≤10 秒，这两个请求按需发起，
    //      Python 侧各缓存 10 分钟，因此**不挂在 `/traffic/weather` 的响应里**；
    //   ③ `force` 是显式参数而不是隐式"每次都刷新" —— 刷新是用户的决定，不是默认行为。
    @GetMapping("/traffic/weather/observations")
    public ResponseEntity<?> weatherObservations(@RequestParam(required = false) Boolean force) throws Exception {
        return python.decisionRequest("/traffic/weather/observations" + (Boolean.TRUE.equals(force) ? "?force=true" : ""), null);
    }
    // 各城市**当前**天气（0.11.24 城市气象条）。**第五次**同一形状的缺失 ——
    // 路径比 `{resource}` 白名单多一段，不显式声明就落到 Spring 默认 404，
    // 而 Python 侧 `/traffic/weather/cities` 本身是好的。
    // 前端拿到的是 `{"status":404,"error":"Not Found","path":"/api/traffic/weather/cities"}`，
    // 界面上表现为"城市气象面板不出现"——不会报错、不会红测试。
    @GetMapping("/traffic/weather/cities")
    public ResponseEntity<?> weatherCities(@RequestParam(required = false) Boolean force) throws Exception {
        return python.decisionRequest("/traffic/weather/cities" + (Boolean.TRUE.equals(force) ? "?force=true" : ""), null);
    }

    @GetMapping("/traffic/weather/models")
    public ResponseEntity<?> weatherModels(@RequestParam(required = false) Boolean force) throws Exception {
        return python.decisionRequest("/traffic/weather/models" + (Boolean.TRUE.equals(force) ? "?force=true" : ""), null);
    }
    // 实测雷达瓦片的**中继**入口（0.9.32（Beta） 补上）。
    //
    // 这是同一类缺中间一腿的**第三次**（前两次：`/traffic/weather/mode`、
    // `/traffic/operations/dispose`），但它的表现形式和那两次都不一样，值得写下来：
    //
    // 前两次是"前端写了字面路径、Python 有路由、中间没人补"，所以跨层审计
    // （`tools/maintenance/_audit_gateway_routes.py`）能看见并报 DEAD。这一次
    // **审计看不见这个调用点**：前端写的是
    //     requestJson(relay.postTo || '/api/traffic/radar/tiles', …)
    // （`frontend/src/traffic/radarRelay.js:73`）—— 路径来自**服务端下发的载荷**
    // （`payload.radar.relay.postTo`），不是字面量首参，而审计的正则只认
    // `requestJson('…')` / ``requestJson(`…`)``。于是闸门报"15 个调用、0 个没匹配"
    // 全绿，而线上这个 POST 稳定 404。
    //
    // 症状长这样（2026-10-15 线上实测，服务端下发了 `relay.needed=true`）：
    //   · 浏览器真的去取了瓦片，而且**取到了**（19:00 档两片 200，
    //     19:12/19:06 两档 404 后正确回退 —— 回退逻辑本身是对的）；
    //   · 回传时拿到 Spring 的默认错误响应：
    //     {"status":404,"error":"Not Found","path":"/api/traffic/radar/tiles"}
    //   · 界面只说一句"实测雷达瓦片已取到但后端未接受：请求失败（HTTP 404）"，
    //     于是"服务器出口被源站 403"这条已知背景会把人引向查源站，而缺的是这一腿。
    //     净效果就是那个长期未愈的现象：**实测雷达回波一直不可用**。
    //
    // 与那两个先例一样，显式声明、不写成通配 `**`：通配会让跨层审计失去对象，
    // 下一条新路径再漏时它还是绿的。
    @PostMapping("/traffic/radar/tiles")
    public ResponseEntity<?> radarTilesRelay(@RequestBody Map<String, Object> body) throws Exception {
        return python.decisionRequest("/traffic/radar/tiles", body);
    }
    // 轨1 模型推理（0.10.1（Beta） 接上）。同一形状的缺失，这是**第五次**
    // （前四次：`weather/mode`、`operations/dispose`、`radar/tiles`、`weather/observations|models`）。
    //
    // 这一次形态与它们不同，所以更值得写下来：那四次都是"前端已写路径、Python 有路由、
    // 中间没人补"，跨层审计能看见。这一次前端**还没有调用点**（研判卡是 0.10.1 才出现的），
    // 于是审计现在扫不到它 —— 先补这一腿，研判卡接上时审计才有对象可查。
    //
    // 两条纪律：
    //   ① 推理**不改写**任何航线、**不覆盖**规则判定。融合裁决在 FusionService，安全优先：
    //      规则能否决模型，模型不能否决规则（否则等于让一个 97% 准确的模型去放行禁飞）。
    //   ② 模型缺席时 Python 返回 HTTP 200 + `available=false` + `status=MODEL_NOT_FOUND`。
    //      "没有模型"是正常状态，不是网关故障 —— 这里不能把它改写成 5xx，
    //      否则前端会把"这一版没带模型"读成"后端挂了"，然后去重试一个永远不会成功的请求。
    @PostMapping("/track1/ml")
    public ResponseEntity<?> track1Ml(@RequestBody Map<String, Object> body) throws Exception {
        ResponseEntity<?> resp = python.decisionRequest("/track1/ml", body);
        // 留痕走旁路：record 内部吞异常，写不进去只记日志（见 MlInferenceRecorder 第 1 条纪律）。
        mlRecorder.record(body, resp.getBody());
        return resp;
    }
    @GetMapping("/track1/ml/status")
    public ResponseEntity<?> track1MlStatus() throws Exception {
        return python.decisionRequest("/track1/ml/status", null);
    }
    /**
     * 轨1 成效汇总（档位分布 / 与规则一致性 / 模型可用率）。
     *
     * <p>这三个数在<b>本机库</b>里（{@code ml_inference} 表），不在 Python 侧，
     * 所以这条不转发；窗口默认 24 小时，上限 720 小时（30 天）——
     * 再长的窗口在这个演示规模下只会把"最近有没有变化"埋进总量里。</p>
     */
    @GetMapping("/track1/ml/summary")
    public ResponseEntity<?> track1MlSummary(@RequestParam(required = false) Integer hours) {
        int window = (hours == null || hours <= 0) ? 24 : Math.min(hours, 720);
        return ResponseEntity.ok(mlRecorder.summary(window));
    }
    /**
     * 轨1 一次完整裁决：规则 → 模型 → 融合。研判卡只发这一个请求。
     *
     * <p>为什么不让前端各发两个请求再自己比档位：见 {@code Track1Service} 的类注释 ——
     * 一句话，"模型不能把禁飞改成可飞"是安全规则，不是展示逻辑，不能有两份实现。</p>
     *
     * <p>规则拒判（要素缺失或越界）返回 **422**，不返回一个兜底档位。
     * 这条以前踩过：`except ValueError: level = 'FIT'` 让基线"白捡"正确率，
     * 界面上还看不出区别 —— 而真相是那一轮根本没量成。</p>
     */
    @PostMapping("/track1/arbitrate")
    public ResponseEntity<?> track1Arbitrate(@RequestBody Map<String, Object> body) {
        try {
            return ResponseEntity.ok(track1.arbitrate(body));
        } catch (IllegalArgumentException ex) {
            return ResponseEntity.unprocessableEntity().body(Map.of(
                    "code", "TRACK1_RULE_ABSTAINED",
                    "message", String.valueOf(ex.getMessage()),
                    "retryable", false));
        } catch (Exception ex) {
            return ResponseEntity.status(502).body(Map.of(
                    "code", "TRACK1_UPSTREAM_FAILED",
                    "message", "轨1 推理失败：" + ex.getClass().getSimpleName(),
                    "retryable", true));
        }
    }
    @GetMapping("/observations")
    public ResponseEntity<?> observations() throws Exception { return python.decisionRequest("/observations", null); }

    // ---- 0.11.1 概率层（换芯）------------------------------------------------
    //
    // 这一组端点是 `/traffic/v2/*`，与上面的 `{resource}` 白名单**不同前缀**，所以
    // 不会互相吞掉。为什么另开一组而不是扩白名单：v2 的字段语义与 v1 不同
    // （`p_unsafe` 是概率、`samples[].km` 是沿航线里程），把两者塞进同一个路径
    // 命名空间会让"这个字段是档位还是概率"只能靠记。
    //
    // 纪律与轨1 一致：模型/观测缺席时 Python 返回 200 + `available:false`，
    // 这里不改写成 5xx —— "三站 METAR 取不到"是正常状态，不是网关故障。
    @GetMapping("/traffic/v2/{resource:overview|corridors|modelcard|counterfactual|divergences|explain}")
    public ResponseEntity<?> trafficV2(@PathVariable String resource,
                                       @RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/v2/" + resource + (query.isEmpty() ? "" : "?" + query), null);
    }

    // 0.11.6（E-2）：真实健康与指标。
    //
    // **为什么这不叫 /healthz**：`/healthz` 在 nginx 里是 `return 200 "ok\n"`，
    // 它连 Java 都没碰过 —— 后端全挂了它也回 ok。改它要动共享 snippet（会影响
    // 同机的 hongsight），所以新增一条 `GET /api/traffic/health`，由 nginx 的
    // `/health` 转发过来；`/healthz` 保留但文档里标注"不反映后端"。
    @GetMapping("/traffic/health")
    public ResponseEntity<?> trafficHealth() throws Exception {
        return python.decisionRequest("/traffic/health", null);
    }

    @GetMapping("/traffic/metrics")
    public ResponseEntity<String> trafficMetrics() throws Exception {
        // 用 rawGet 而不是 decisionRequest：后者会把 body 当 JSON 解析，而这里是
        // Prometheus 的文本格式 —— 解析失败会让这个端点 500（实测过）。
        return python.rawGet("/traffic/metrics");
    }

    // 0.11.6（E-1②③）：台账翻页与按需取航迹。
    // 注意路径是 `flights`（复数）与 `flights/points`，与下面的 `flight/{id}`（单数）
    // 不冲突 —— 但**顺序**要注意：Spring 的精确路径优先于路径变量，所以放前面更稳。
    @GetMapping("/traffic/flights")
    public ResponseEntity<?> trafficFlights(@RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/flights" + (query.isEmpty() ? "" : "?" + query), null);
    }

    @GetMapping("/traffic/flights/points")
    public ResponseEntity<?> trafficFlightsPoints(@RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/flights/points" + (query.isEmpty() ? "" : "?" + query), null);
    }

    @GetMapping("/traffic/flight/{id}")
    public ResponseEntity<?> trafficFlight(@PathVariable String id,
                                           @RequestParam Map<String, String> params) throws Exception {
        // 0.11.5（W-31）：首屏用 `fields=slim` 拿到裁剪过的计划，选中某一班时用这条补全
        // （许可报文、静态空域、完整航迹）。**没有这条路由时前端会 404**，
        // 而 404 在界面上长得像"这条班次不存在"—— 所以工具链闸门专门盯着
        // "前端调了、网关没转发"这一类，它就是在这里把这条拦下来的。
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/flight/" + encode(id)
                + (query.isEmpty() ? "" : "?" + query), null);
    }

    @GetMapping("/traffic/v2/corridor/{id}")
    public ResponseEntity<?> trafficV2Corridor(@PathVariable String id,
                                               @RequestParam Map<String, String> params) throws Exception {
        // 0.11.4（W-13f）：这一条原来**没有 `@RequestParam Map`**，于是
        // `/api/traffic/v2/corridor/CAR-x?case=fog-20250105` 的 `case` 在网关层
        // 就被丢掉了 —— Python 侧明明支持 case，前端也传了，但到了后端永远是实时场。
        // 症状很隐蔽：走廊页"观测"一栏显示的是此刻，而首页写着 2025-01-05。
        // 通配的 `/traffic/v2/{resource}` 已经透传 query，这条是漏网的特例。
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue()))
                .collect(Collectors.joining("&"));
        return python.decisionRequest("/traffic/v2/corridor/" + encode(id)
                + (query.isEmpty() ? "" : "?" + query), null);
    }

    /** 一次裁决落账（采纳 / 否决 / 回滚）。理由必填 —— 没有理由的否决无法审计。 */
    @PostMapping("/traffic/v2/decision")
    public ResponseEntity<?> trafficV2Decision(@RequestBody Map<String, Object> body) throws Exception {
        Object note = body.get("note");
        if (note == null || String.valueOf(note).isBlank()) {
            return ResponseEntity.unprocessableEntity().body(Map.of(
                    "code", "DECISION_NOTE_REQUIRED",
                    "message", "否决或回滚必须填写理由",
                    "retryable", false));
        }
        return python.decisionRequest("/traffic/v2/decision", body);
    }

    @GetMapping("/workspace/frame")
    public ResponseEntity<?> frame(@RequestParam Map<String, String> params) throws Exception {
        String query = params.entrySet().stream().map(e -> encode(e.getKey()) + "=" + encode(e.getValue())).collect(Collectors.joining("&"));
        return python.decisionRequest("/workspace/frame?" + query, null);
    }
    @PostMapping("/tasks/evaluate")
    public ResponseEntity<?> evaluate(@RequestBody Map<String, Object> body) throws Exception { return python.decisionRequest("/tasks/evaluate", body); }
    @PostMapping("/decisions/explain")
    public ResponseEntity<?> explain(@RequestBody Map<String, Object> body) throws Exception { return python.decisionRequest("/decisions/explain", body); }
    @GetMapping("/decisions")
    public ResponseEntity<?> history() throws Exception { return python.decisionRequest("/decisions", null); }
    @GetMapping("/decisions/{id:[a-f0-9]{64}}")
    public ResponseEntity<?> decision(@PathVariable String id) throws Exception { return python.decisionRequest("/decisions/" + id, null); }
    @GetMapping("/replays/{id:[a-f0-9]{64}}")
    public ResponseEntity<?> replay(@PathVariable String id) throws Exception { return python.decisionRequest("/replays/" + id, null); }
    @GetMapping("/system/version")
    public Map<String, Object> version() throws Exception {
        // 这里原来写的是 `Map.of("version", "1.2.0", …)` —— 一个与产品版本毫无关系的字面量。
        // 它会被写进运维对照表（`docs/local-v1.md` 就把这条列成了"前后端版本"），
        // 于是"磁盘上是 0.10.1、接口说 1.2.0"这种事只能靠人记。改为读 VERSION 文件：
        // `start.bat` 保证工作目录是工程根，读不到就返回 unknown —— **不编版本号**。
        Map<String, Object> out = new java.util.LinkedHashMap<>();
        out.put("version", productVersion());
        out.put("mode", "LOCAL_SOURCE");
        out.put("python", python.decisionRequest("/health", null).getBody());
        return out;
    }

    /** 产品版本：工程根 `VERSION` 文件的第一行。读不到返回 {@code unknown}。 */
    private String productVersion() {
        try {
            java.nio.file.Path p = java.nio.file.Path.of("VERSION");
            if (java.nio.file.Files.isRegularFile(p)) {
                String v = java.nio.file.Files.readString(p, StandardCharsets.UTF_8).trim();
                if (!v.isEmpty()) return v;
            }
        } catch (Exception ignored) {
            // 读不到就是读不到。返回 unknown 而不是回落到某个硬编码值。
        }
        return "unknown";
    }
    private String encode(String value) { return URLEncoder.encode(value, StandardCharsets.UTF_8); }
}
