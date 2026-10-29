package com.tianchuang.service;
import com.tianchuang.dto.LayerDto;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

/** Python owns spatial calculations; Java binds results to the dashboard identity. */
@Service
public class LayerService {
    private final MonitorService monitor;
    private final PythonClient python;
    public LayerService(MonitorService monitor, PythonClient python) { this.monitor = monitor; this.python = python; }
    public List<LayerDto> layers(String regionId, String runId, Integer requestedRevision) {
        Map<String, Object> dashboard = monitor.buildDashboard();
        if (runId == null || !runId.equals(dashboard.get("runId"))) throw new ResourceNotFoundException("指定运行不存在或已不是当前运行");
        if (regionId != null && !regionId.isBlank() && !regionId.equals(dashboard.get("regionId"))) throw new ResourceNotFoundException("指定作业区不存在");
        int revision = dashboard.get("revision") instanceof Number n ? n.intValue() : 0;
        if (requestedRevision != null && requestedRevision != revision) throw new LayerVersionConflictException("图层版本已更新，请重新获取当前Dashboard");
        if (!(dashboard.get("current") instanceof Map<?, ?>)) return List.of();
        try {
            List<LayerDto> result = python.weatherLayers(dashboard);
            if (result == null || result.stream().anyMatch(layer -> !runId.equals(layer.runId()) || revision != layer.revision())) throw new IllegalStateException("天气返回版本不一致");
            return result;
        } catch (Exception e) { throw new IllegalStateException("天气图层暂不可评估", e); }
    }
    public static class ResourceNotFoundException extends IllegalArgumentException { public ResourceNotFoundException(String message) { super(message); } }
    public static class LayerVersionConflictException extends IllegalStateException { public LayerVersionConflictException(String message) { super(message); } }
}
