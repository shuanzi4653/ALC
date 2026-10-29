# `config/nginx/` —— 服务器侧配置快照

这个目录里放**从生产服务器 pull 下来的 nginx 片段**，供闸门里的
`_audit_quota_coverage.py` 比对「Java 的计费名单」与「nginx 的限速名单」。

## 为什么它在这里

原先那份快照住在 `.run/cloud/`。而 `.run/` 是**每轮清理都会整目录删掉**的临时区 ——
于是 2026-10-18 清理之后，配额审计立刻报 `BLIND: No such file …`，读起来像"配置坏了"，
真相是**审计的输入被删掉了**（见 `changelog/ISSUES.md` **M93**；
同族的第一次是 **ISS-0.9.26-06**：发布脚本住在 `.run/`）。

**闸门要读的配置事实必须和 `config/rules-v1.json` / `config/labels-v1.json` 住在一起**：
它们一起进交付包、一起被清理规则豁免、也一起被"当前是哪个版本"这类判据读到。

## 期望的文件

```
config/nginx/AIC-tianchuang-upstream.conf
```

里面至少要有这一段（`map "$request_method $uri"` ＋ 若干 `"~^POST /api/…$"`）：

```nginx
map "$request_method $uri" $AIC_tianchuang_llm_key {
    "~^POST /api/decisions/explain$"   "1";
    "~^POST /api/traffic/explain$"     "1";
}
```

## 怎么取

```bash
ssh <user>@62.234.154.34 'cat /etc/nginx/conf.d/*upstream*.conf' > config/nginx/AIC-tianchuang-upstream.conf
```

（路径以服务器上的实际文件名为准；本仓只约定**落在本目录**。）

## 快照缺席时的行为

审计**不会**报「两份名单一致」，也不会长期红灯：

- 打印 `-- skipped (nginx snapshot absent: config/nginx/AIC-tianchuang-upstream.conf)`；
- 退出码 **2**（无法测量），与 1（量出问题）分开；
- 闸门只接受上面**这一个**词，`-- cannot measure` 仍然继续红；
- `--self-test` 在快照缺席时改用**从 Java 名单合成的 map 块**，并打印用的是哪一份 ——
  自检不该依赖被检查对象的数据。

**换句话说：没量过就不会被读成量过。**
