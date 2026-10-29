#!/usr/bin/env bash
# =============================================================================
# verify-remote.sh —— 线上判据（37 项）
#
# !!! 这个文件必须在**服务器上**跑，不能在本机跑 !!!
#   它测的是 https://tianchuang.shuanzi.site 与内层回环端口（28081/28083），
#   本机跑不通那两条链路，结果会一片 FAIL 而分不清是环境还是代码。
#     服务器上：  cd /opt/apps/AIC-tianchuang && bash bin/verify-remote.sh
#
# 判据覆盖：A 公网端口收敛 / B 匿名首页（200 且无 Location）/ C 内层只绑回环 /
#           D 静态资源可达 / E 接口与配额 / F–H 工作区隔离「非空洞八连」+ 配额只读不扣费 /
#           I WebSocket 两跳 101 / J 限速落点
#
# 0.11.6（E-3）改动：`set_mode` 切气象通道时补 `X-ALC-Operator: admin`。
#   操作级授权上线后，这个运维脚本代表管理员；不带身份会被 403 —— 而那是**正确行为**，
#   所以修的是脚本，不是把规则降级。
#
# 曾经它只存在于服务器 `/opt/apps/AIC-tianchuang/bin/`，仓库里没有源：
# 重装即丢失、改动无法追溯。这个副本就是为了让"线上判据"也进版本管理。
# 仓库副本与服务器副本**必须逐字节一致**，判据见 tools/maintenance/_check_ops_parity.py
# =============================================================================
#!/usr/bin/env bash
# =============================================================================
# AIC-tianchuang —— 端到端核对（**在服务器上执行**）
# 判据集合与 docs/云端部署与运维说明.md §8.1 一一对应。
#
# 用法：
#   sudo bash verify-remote.sh
#
# 2026-10-18 改版要点：鉴权门已于 2026-10-14 拆除，而本脚本原先把「302 去 /login」
# 写死进判据 —— 于是把**当前正确状态**判成 9 条 FAIL。其中「令牌出现 98 次」
# 最值得记：`TOK` 取到空串后 `grep -c "$TOK"` 匹配了每一行，判据自己成了变量。
# 现已迁到「匿名工作区」口径，且**牙齿一条没拔**：不许出现跳转、门不许复活、
# WS 两跳都要 101、工作区隔离必须非空洞（切 A 后 B 与未标识都不许变）。
#
# 2026-10-14 改版要点（入口从 IP:28081 变成 https://tianchuang.shuanzi.site/）：
#   ① 判据分三层：内层回环(28081) / 公网域名(443) / 端口暴露面。三层都要看 ——
#      只测内层会把"外层 443 块的毛病"整个漏掉（§7.5 的 WS 就是这么漏的）。
#   ② 3xx 判据必须连 Location 的值一起判（§7.8）。只判状态码会放过
#      `Location: http://域名:28081/login` 这种"状态对、落点是死的"。
#   ③ 本脚本**给出裁决并据以设置退出码**（任一 FAIL ⇒ exit 1）。
#      只打印不判的核对等于没核对：输出要人去读，读漏了不会变红（§17）。
# =============================================================================
set -uo pipefail

R=/opt/apps/AIC-tianchuang
BASE="${ALC_BASE_URL:-https://tianchuang.shuanzi.site}"
TMPD="/tmp/aic-verify.$$"
mkdir -p "$TMPD"
trap 'rm -rf "$TMPD" 2>/dev/null || true' EXIT

PASS=0; FAIL=0; SKIP=0
ok()   { PASS=$((PASS+1)); printf '  PASS  %s（%s）\n' "$1" "${2:-}"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL  %s（期望 %s，实得 %s）\n' "$1" "$2" "$3"; }
skip() { SKIP=$((SKIP+1)); printf '  SKIP  %s（%s）\n' "$1" "${2:-原因未给出 —— 此项未测，不等于通过}"; }
# 判状态码
chk() { [ "$2" = "$3" ] && ok "$1" "$3" || bad "$1" "$2" "$3"; }
code() { curl -s -o /dev/null -w '%{http_code}' -m 12 "$@"; }
# 头名大小写不敏感：HTTP/1.1 给 `Location:`，HTTP/2 给 `location:`（全小写）。
# 本机 curl 与服务器 curl 协商的协议版本可能不同，附大小写的匹配会让判据本身变成变量。
loc()  { curl -sI -m 12 "$@" | tr -d '\r' | awk -F': *' 'tolower($1)=="location"{print $2}'; }

echo "=========== A. 单元状态 ==========="
systemctl is-active AIC-tianchuang AIC-tianchuang-python nginx mysql

echo
echo "=========== B. 端口绑定（判「听在哪个地址」，不判「有没有在听」）==========="
# 内层三个端口必须**只在回环**；80/443 才是公网面。
for p in 80 443 28081 28082 28083; do
    A=$(sudo ss -lnt "sport = :$p" 2>/dev/null | awk 'NR>1{print $4}' | paste -sd, -)
    printf '  %-6s %s\n' "$p" "${A:-free}"
done
for p in 28081 28082 28083; do
    A=$(sudo ss -lnt "sport = :$p" 2>/dev/null | awk 'NR>1{print $4}')
    if [ -z "$A" ]; then bad "端口 $p 有监听" "有 127.0.0.1 监听" "(无)"
    elif echo "$A" | grep -q '^0\.0\.0\.0' || echo "$A" | grep -q '^\*'; then
        bad "端口 $p 仅在回环" "127.0.0.1" "$(echo "$A" | paste -sd, -)"
    else ok "端口 $p 仅在回环" "$(echo "$A" | paste -sd, -)"; fi
done

echo
echo "=========== C. default_server 归属 ==========="
# 不变量是「**只有一个站点文件**拥有 default_server」，不是「匹配行数 = 1」：
# 同一站点里 `listen 80 default_server;` 与 `listen [::]:80 default_server;`
# 各一条是合法的 v4+v6 写法（hongsight 实测 2 行 1 属主）。
# 早前这里判行数，于是把一个**正常**状态判成 FAIL —— 而 verify-static-remote.sh
# 判的是属主文件数、判对了。同一个不变量被两处判据给出相反结论时，
# 至少有一处写错了；以"和事实语义对得上"的那条为准（此处是文件数）。
# 另外必须用 -R：`grep -r` 不跟随 sites-enabled 里的符号链接，会读出假 0。
owners=$(grep -RlE '^[^#]*default_server' /etc/nginx/sites-enabled/ 2>/dev/null | sort -u)
printf '  属主文件：%s\n' "$(printf '%s' "$owners" | tr '\n' ' ')"
N=$(printf '%s' "$owners" | grep -c .)
chk "default_server 属主文件数" 1 "$N"

echo
echo "=========== D. Java 直连（回环 28082）==========="
for p in /api/health/live /api/health/ready /api/config/status; do
    printf '  %-22s ' "$p"
    curl -s -o "$TMPD/o.json" -w 'HTTP %{http_code} %{time_total}s ' -m 10 "http://127.0.0.1:28082$p"
    head -c 300 "$TMPD/o.json"; echo
done

echo
echo "=========== E. Python 直连（回环 28083）==========="
printf '  /health                '
curl -s -o "$TMPD/p.json" -w 'HTTP %{http_code} %{time_total}s ' -m 10 "http://127.0.0.1:28083/health"
head -c 300 "$TMPD/p.json"; echo

echo
echo "=========== F. 内层 Nginx（http://127.0.0.1:28081）==========="
chk "内层 /healthz 免鉴权" 200 "$(code http://127.0.0.1:28081/healthz)"
# 2026-10-18：这里以前是「无会话 → 302 去登录」。门在 2026-10-14 已拆除，
# 所以当前正确状态是「就地 200、不产生任何跳转」。判据保持同样的**意图**：
# 证明它自己能应答，且没把浏览器往外推。
chk "内层 / 匿名 → 200"    200 "$(code http://127.0.0.1:28081/)"
chk "内层 /login → 404"    404 "$(code http://127.0.0.1:28081/login)"

echo
echo "=========== G. 公网入口（$BASE）==========="
chk "http → 301"            301 "$(code -H 'Host: tianchuang.shuanzi.site' http://62.234.154.34/)"
chk "https / 匿名 → 200"    200 "$(code "$BASE/")"
L=$(loc "$BASE/")
[ -z "$L" ] && ok "无 Location（没有可泄漏、也没有可跟随的跳转）" \
            || bad "重定向落点" "无 Location" "$L ← 门已拆，出现跳转说明有人把它装回来了（docs §7.8）"
chk "https /login → 404"    404 "$(code "$BASE/login")"
chk "https /sz-auth → 404"  404 "$(code "$BASE/sz-auth")"
chk "https /healthz 匿名"   200 "$(code "$BASE/healthz")"
BODY=$(curl -s -m 12 "$BASE/")
TITLE=$(printf '%s' "$BODY" | grep -o '<title>[^<]*</title>' | head -1)
[ -n "$TITLE" ] && ok "首页有 title" "$TITLE" || bad "首页内容" "含 <title>" "(空或异常)"
printf '%s' "$BODY" | grep -qE 'assets/index-[^"]+\.js' \
    && ok "首页引用了主包" "assets/index-*.js" \
    || bad "首页引用主包" "assets/index-*.js" "(首页里没有)"

echo
echo "=========== H. 匿名工作区隔离（取代 2026-10-14 拆除的表单登录）==========="
# 门拆掉之后，服务端能区分调用方的东西只剩 X-ALC-Workspace 一个来源，
# 而「空值 = 未标识」，**不是**一个默认工作区。这里要证隔离**非空洞**：
#   ① 两个全新工作区都必须等于默认 measured（不是「查不到 / 未设置」）
#   ② 切换 A 之后，B 与未标识**都不许跟着变**
# 只测「A 变了」这一半是没有牙齿的：一个完全不隔离的实现也能让 A 变。
MS=http://127.0.0.1:28082/api/traffic/weather/mode
mode_of() {
    if [ -n "$1" ]; then
        curl -s -m 12 -H "X-ALC-Workspace: $1" "$MS"
    else
        curl -s -m 12 "$MS"
    fi | grep -o '"mode":"[a-z]*"' | head -1 | cut -d'"' -f4
}
set_mode() {
    local body="{\"mode\":\"$1\"}"
    if [ -n "$2" ]; then
        curl -s -o /dev/null -w '%{http_code}' -m 12 -X POST -H "X-ALC-Workspace: $2" -H "X-ALC-Operator: admin" \
             -H 'Content-Type: application/json' -d "$body" "$MS"
    else
        curl -s -o /dev/null -w '%{http_code}' -m 12 -X POST \
             -H 'Content-Type: application/json' -d "$body" "$MS"
    fi
}
TAG=$(date +%H%M%S)
WA="probe${TAG}a"; WB="probe${TAG}b"
chk "全新工作区 A 的默认口径" measured "$(mode_of "$WA")"
chk "全新工作区 B 的默认口径" measured "$(mode_of "$WB")"
chk "未标识调用方的口径"      measured "$(mode_of "")"
chk "把 A 切到 virtual"       200      "$(set_mode virtual "$WA")"
chk "A 已变"                  virtual  "$(mode_of "$WA")"
chk "B 不受影响"              measured "$(mode_of "$WB")"
chk "未标识不受影响"          measured "$(mode_of "")"
chk "把 A 切回 measured"      200      "$(set_mode measured "$WA")"
chk "A 已复原"                measured "$(mode_of "$WA")"
# 配额端点是只读的：连打两次 remaining 不许变（「只读不扣费」的牙齿）。
Q1=$(curl -s -m 12 http://127.0.0.1:28082/api/quota | grep -o '"remaining":[0-9]*' | head -1 | cut -d: -f2)
Q2=$(curl -s -m 12 http://127.0.0.1:28082/api/quota | grep -o '"remaining":[0-9]*' | head -1 | cut -d: -f2)
[ -n "$Q1" ] && [ "$Q1" = "$Q2" ] && ok "GET /api/quota 只读不扣费" "remaining=$Q1 两次相同" \
                                  || bad "GET /api/quota 只读不扣费" "两次 remaining 相同" "Q1=$Q1 Q2=$Q2"

echo
echo "=========== I. WebSocket（§7.5：两跳都要 101）==========="
WSKEY='Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ=='
IN=$(curl -s -o /dev/null --http1.1 -m 8 -w '%{http_code}' \
     -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H "$WSKEY" \
     http://127.0.0.1:28081/ws/dashboard)
chk "内层 WS → 101" 101 "$IN"
OUT=$(curl -s -o /dev/null --http1.1 -m 8 -w '%{http_code}' \
     -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H "$WSKEY" \
     "$BASE/ws/dashboard")
chk "经 443 WS → 101" 101 "$OUT"
# 探针不带 Origin 也能过，但浏览器**一定**会带 —— 白名单缺域名只在带 Origin 时才现形。
OUTO=$(curl -s -o /dev/null --http1.1 -m 8 -w '%{http_code}' \
     -H 'Connection: Upgrade' -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' -H "$WSKEY" \
     -H "Origin: $BASE" "$BASE/ws/dashboard")
chk "经 443 WS 带 Origin → 101" 101 "$OUTO"
[ "$OUT" = 101 ] && [ "$OUTO" != 101 ] && \
    echo "        ↳ 无 Origin 过、带 Origin 不过 ⇒ Java 白名单缺域名（docs §10.3）：探针过 ≠ 浏览器过"

echo
echo "=========== J. gzip 经域名（主包压缩比）==========="
JS=$(printf '%s' "$BODY" | grep -oE 'assets/index-[^"]+\.js' | head -1)
if [ -z "$JS" ]; then
    bad "找到主包路径" "assets/index-*.js" "(首页里没有)"
else
    RAW=$(curl -s -m 30 -H 'Accept-Encoding: identity' -o /dev/null -w '%{size_download}' "$BASE/$JS")
    GZ=$(curl -s -m 30 -H 'Accept-Encoding: gzip'   -o /dev/null -w '%{size_download}' "$BASE/$JS")
    printf '  %s：%s → %s B\n' "$JS" "$RAW" "$GZ"
    [ "$GZ" -lt "$RAW" ] && ok "主包被压缩" "$(awk "BEGIN{printf \"%.2fx\", $RAW/$GZ}")" \
                         || bad "主包被压缩" "GZ < RAW" "$GZ >= $RAW"
fi

echo

echo "=========== K. 端口暴露面（28081 必须公网不可达）==========="
# 判 curl 的**退出码**：7=连接被拒 / 28=超时；0=居然连上了。
# 不要判 -w 的 http_code 再拼字符串 —— curl 在连不上时本来就打 000（§8.1 记录过这次判据自误）。
curl -s -o /dev/null --noproxy '*' -m 8 http://62.234.154.34:28081/ 2>/dev/null; RC=$?
case "$RC" in
  7|28) ok "公网 28081 不可达" "curl rc=$RC";;
  0)    bad "公网 28081 不可达" "拒绝或超时" "rc=0，居然连上了 —— 内网没收干净";;
  *)    printf '  WARN  公网 28081 判据异常（curl rc=%s，既非通也非拒）—— 需人看\n' "$RC";;
esac

echo
echo "=========== L. 邻居未受影响（本项目只应动自己的块）==========="
printf '  hongsight :80  '; curl -s -o /dev/null -w 'HTTP %{http_code}\n' -m 8 http://127.0.0.1/api/system/ping
printf '  hongsight 域名 '; curl -s -o /dev/null -w 'HTTP %{http_code}\n' -m 8 https://hongsight.shuanzi.site/healthz 2>/dev/null
printf '  ice 域名       '; curl -s -o /dev/null -w 'HTTP %{http_code}\n' -m 8 https://ice.shuanzi.site/ 2>/dev/null
printf '  证书到期       '
echo | openssl s_client -connect tianchuang.shuanzi.site:443 -servername tianchuang.shuanzi.site 2>/dev/null \
  | openssl x509 -noout -subject -enddate 2>/dev/null | tr '\n' ' '; echo

echo
echo "=========== M. 配置面一致性（防「改了文件但没生效」）==========="
NA=/etc/nginx/sites-available/AIC-tianchuang
printf '  站点块 listen      : '; grep -E '^[[:space:]]*listen' "$NA" | tr -s ' ' | tr '\n' ' '; echo
printf '  站点块 server_name : '; grep -E '^[[:space:]]*server_name' "$NA" | tr -s ' '
printf '  相对重定向         : '; grep -q 'absolute_redirect off;' "$NA" && echo "已设（相对 Location）" || echo "!! 未设 → Location 会带 :28081（docs §7.8）"
# ⚠️ 数指令必须**剔注释**：段落里保留着解释历史故障的注释，其中逐字含
#    `$AIC_tianchuang_connection` 与 `Connection ""`。对整段 grep 会把注释算成"配置"，
#    于是"配置还在不在"这个判据被注释永久染绿/染红。（实测踩到过，见 docs §7.9）
SEGBODY=$(sudo python3 -c '
import io,sys
B="# ============================== \u5929\u7a97\u667a\u5de1 AIC =============================="
E="# ============================== \u51b0\u96ea\u6587\u65c5 ICE_Travel =============================="
t=io.open("/etc/nginx/sites-available/domains",encoding="utf-8").read()
s=t[t.index(B):t.index(E,t.index(B))]
print("\n".join(l for l in s.splitlines() if not l.lstrip().startswith("#")))' 2>/dev/null)
NW=$(printf '%s' "$SEGBODY" | grep -c 'AIC_tianchuang_connection')
chk "domains 正文里 WS 透传指令数" 1 "$NW"
printf '%s' "$SEGBODY" | grep -q 'Connection ""' \
    && bad "domains 正文里无 Connection \"\"" "无" "有（WS 会 400）" \
    || ok "domains 正文里无 Connection \"\""
# 2026-10-18：门拆掉之后 `aic_session=` 在站点块里根本不存在，旧写法取到的是**空串**，
# 随后 `grep -c "$TOK"` 用空模式匹配了每一行 —— 于是报「期望 1、实得 98」。
# 一条判据把自己变成了变量。现在直接数字面量：门不该回来，期望就是 0。
# 数指令必须**剔注释**：片段里留着解释历史故障的注释，其中逐字含 `cookie_aic_session`。
# 对整份文件 grep 会把注释算成"配置"，于是「门有没有回来」这条判据被一行注释染红。
SITE_LIVE=$(grep -v '^[[:space:]]*#' "$NA" | grep -c 'aic_session' || true)
SNIP_LIVE=$(grep -v '^[[:space:]]*#' /etc/nginx/snippets/AIC-tianchuang-api.conf | grep -c 'aic_session' || true)
chk "站点块内会话令牌残留（已剔注释）" 0 "$SITE_LIVE"
chk "片段内会话门残留（已剔注释）"     0 "$SNIP_LIVE"

echo
echo "=========== N. 关键日志尾部 ==========="
echo "--- AIC-tianchuang (Java) ---"; journalctl -u AIC-tianchuang -n 12 --no-pager | tail -12
echo "--- AIC-tianchuang-python ---"; journalctl -u AIC-tianchuang-python -n 8 --no-pager | tail -8
echo "--- nginx error.log（最近 8 行；出现 still could not bind 说明有新配置没生效）---"
tail -8 /var/log/nginx/error.log
# ⚠️ 判据必须**限定时间窗**。早前的写法是"最近 50 行里有没有 still could not bind"——
#    结果 18:19 那次失败 reload 的记录（`still could not bind`）在 20:29 还被算作
#    "当前有新配置没生效"，把已经修好的现状判成了 FAIL。
#    这是"参照物过期"导致的**假失败**（与 docs §7.6/§17 同类）：
#    判据要问的是"**这次**应用有没有生效"，不是"历史上有没有失败过"。
#    日志时间戳格式 `YYYY/MM/DD HH:MM:SS` 定宽，字典序比较即等价于时间比较。
CUT=$(date -d '15 minutes ago' '+%Y/%m/%d %H:%M')
RECENT=$(awk -v cut="$CUT" '{ ts=substr($1" "$2,1,16); if (ts >= cut) print }' /var/log/nginx/error.log 2>/dev/null)
HITS=$(printf '%s' "$RECENT" | grep -c 'still could not bind' || true)
chk "近 15 分钟内无 bind 失败" 0 "$HITS"
if [ "${HITS:-0}" != 0 ]; then
    echo "        ↳ 命中的行："; printf '%s\n' "$RECENT" | grep 'still could not bind' | sed 's/^/          /'
    echo "        ↳ 处理：改过 listen 地址时 reload 会静默不生效，需 sudo systemctl restart nginx（§7.6）"
fi

echo
echo "=========== O. 资源占用 ==========="
free -m | head -2
systemd-cgtop -m -n 1 --order=memory 2>/dev/null | head -8
df -h /opt | tail -1
du -sh "$R" "$R"/backend-python/.venv "$R"/app 2>/dev/null

echo
echo "=========== P. 凭据面（「密钥不许明码」的牙齿在这一节）==========="
echo "--- 权限（期望：.env 600 / .env.secrets 600 / config 700 / application.yml 600 / *.pem 600）---"
stat -c '%a %U:%G %n' "$R/.env" "$R/.env.secrets" "$R/config" "$R/config/application.yml" 2>&1
ls -l "$R/config/qweather/" 2>&1
echo "--- 明文扫描①：config/ 下不得出现 sk- 开头的 api-key ---"
if grep -rInE 'api-key:[[:space:]]*"?sk-' "$R/config/" 2>/dev/null; then
    bad "config/ 无明文 api-key" "无" "有（见上）"
else ok "config/ 无明文 api-key"; fi
echo "--- 明文扫描②：项目目录内不得出现明文 BASIC_AUTH_PASS 赋值 ---"
if sudo grep -rIn --binary-files=without-match \
        --exclude='*.db' --exclude='*.jar' --exclude='*.gz' --exclude='*.tar' \
        -E 'BASIC_AUTH_PASS=[A-Za-z0-9]{12,}' "$R" 2>/dev/null; then
    bad "项目目录无明文 BASIC_AUTH_PASS" "无" "有（见上）"
else ok "项目目录无明文 BASIC_AUTH_PASS"; fi
echo "--- htpasswd 本体（应只有 apr1 哈希，明文不在盘上）---"
sudo awk -F: '{print "  " $1 ": <hash " length($2) " chars>"}' /etc/nginx/.htpasswd-AIC-tianchuang 2>/dev/null
echo "--- 两侧消费点是否指向同一个键名（改一处必查另一处）---"
grep -n 'DEEPSEEK_API_KEY' "$R/config/application.yml" 2>/dev/null || echo "  (application.yml 未用占位符 —— 异常)"
grep -n 'os.getenv("DEEPSEEK_API_KEY"' "$R/backend-python/main.py" 2>/dev/null || echo "  (main.py 未用 os.getenv —— 异常)"
echo "--- 密钥是否真的被读到（只回布尔，不回显密钥）---"
curl -s -m 10 http://127.0.0.1:28083/health 2>/dev/null | head -c 300; echo

echo
echo "============================================================"
printf '裁决：PASS %d / FAIL %d / SKIP %d\n' "$PASS" "$FAIL" "$SKIP"
if [ "$FAIL" -gt 0 ]; then
    echo "结论：**未通过**（上面每条 FAIL 都要处理；SKIP 项未测，不算通过）"
    exit 1
fi
if [ "$SKIP" -gt 0 ]; then
    echo "结论：已测项全过；有 $SKIP 项**未测** —— 未测不等于通过，需人看"
    exit 2
fi
echo "结论：全过"
