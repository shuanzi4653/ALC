package com.tianchuang.controller;

import com.tianchuang.dto.LayerDto;
import com.tianchuang.service.LayerService;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/layers")
public class LayerController {
    private final LayerService layers;

    public LayerController(LayerService layers) { this.layers = layers; }

    @GetMapping
    public List<LayerDto> get(@RequestParam(required = false) String regionId,
                              @RequestParam String runId,
                              @RequestParam(required = false) Integer revision) {
        return layers.layers(regionId, runId, revision);
    }
}
