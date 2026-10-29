package com.tianchuang.controller;

import com.tianchuang.config.QuotaFilter;
import com.tianchuang.config.WorkspaceContext;
import com.tianchuang.service.QuotaService;

import jakarta.servlet.http.HttpServletRequest;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 配额自述接口：调用方读<b>自己</b>的今日用量。
 *
 * <p>它存在的理由是让配额可以被<b>非破坏性地观察</b>。没有它的话，验证"配额在生效"
 * 只能靠真的把 120 次大模型调用打满 —— 那等于为了验证配额去烧配额，而且会真花掉
 * DeepSeek 的额度。有了它，判据可以写成：「读自己的计数 → 调用一次计费端点 →
 * 再读，恰好 +1，且<b>另一个工作区的计数不变</b>」，一共只花一次调用。</p>
 *
 * <p>只返回调用方自己的两格（自己的工作区、自己的出口地址），不返回任何全机汇总或
 * 别人的用量。工作区 id 是客户端生成的随机串，把它填进 {@code X-ALC-Workspace}
 * 就能看到那一格的数字 —— 前提是已经知道那个串。</p>
 */
@RestController
@RequestMapping("/api")
public class QuotaController {

    private final QuotaService quota;

    public QuotaController(QuotaService quota) {
        this.quota = quota;
    }

    @GetMapping("/quota")
    public Map<String, Object> quota(HttpServletRequest request) {
        return quota.status(WorkspaceContext.current(), QuotaFilter.clientAddress(request));
    }
}
