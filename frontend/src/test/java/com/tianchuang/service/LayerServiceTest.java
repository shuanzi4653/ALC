package com.tianchuang.service;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.util.Map;
import java.util.List;
import org.junit.jupiter.api.Test;
class LayerServiceTest {
    @Test void rejectsStaleIdentityBeforeCalculation() {
        MonitorService monitor=mock(MonitorService.class); PythonClient python=mock(PythonClient.class);
        when(monitor.buildDashboard()).thenReturn(Map.of("runId","new","regionId","zone","revision",2,"current",Map.of()));
        LayerService service=new LayerService(monitor,python);
        assertThatThrownBy(()->service.layers("zone","old",2)).isInstanceOf(LayerService.ResourceNotFoundException.class);
        assertThatThrownBy(()->service.layers("zone","new",1)).isInstanceOf(LayerService.LayerVersionConflictException.class);
        verifyNoInteractions(python);
    }
    @Test void doesNotInventWeatherWhenCalculationFails() throws Exception {
        MonitorService monitor=mock(MonitorService.class); PythonClient python=mock(PythonClient.class);
        Map<String,Object> dashboard=Map.of("runId","new","regionId","zone","revision",2,"current",Map.of());
        when(monitor.buildDashboard()).thenReturn(dashboard);
        when(python.weatherLayers(dashboard)).thenThrow(new IllegalStateException("offline"));
        assertThatThrownBy(()->new LayerService(monitor,python).layers("zone","new",2)).isInstanceOf(IllegalStateException.class);
    }
}
