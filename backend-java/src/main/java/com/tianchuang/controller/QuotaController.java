package com.tianchuang.controller;

import com.tianchuang.config.QuotaFilter;
import com.tianchuang.config.WorkspaceContext;
import com.tianchuang.service.QuotaService;

import jakarta.servlet.http.HttpServletRequest;

import java.util.Map;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

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
