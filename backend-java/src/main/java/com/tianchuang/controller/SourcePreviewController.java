package com.tianchuang.controller;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/** Prevent an old generated static directory from appearing as the updated source UI. */
@Controller
@ConditionalOnProperty(name = "local.source-mode", havingValue = "true")
public class SourcePreviewController {
    @GetMapping({"/", "/index.html"})
    public String home() { return "redirect:http://127.0.0.1:5180/"; }
}
