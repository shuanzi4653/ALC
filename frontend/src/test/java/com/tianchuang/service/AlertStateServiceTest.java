package com.tianchuang.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.tianchuang.entity.AlertStateEntity;
import com.tianchuang.model.FlightLevel;
import com.tianchuang.repository.AlertStateRepo;
import java.util.HashMap;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class AlertStateServiceTest {
    private AlertStateService service;

    @BeforeEach
    void setUp() {
        Map<String, AlertStateEntity> states = new HashMap<>();
        AlertStateRepo repo = mock(AlertStateRepo.class);
        when(repo.findByStateKey(any())).thenAnswer(call -> Optional.ofNullable(states.get(call.getArgument(0))));
        when(repo.save(any())).thenAnswer(call -> {
            AlertStateEntity state = call.getArgument(0);
            states.put(state.stateKey, state);
            return state;
        });
        service = new AlertStateService(repo);
    }

    @Test
    void repeatedSameLevelDoesNotRepublish() {
        assertThat(service.evaluate("key", 1, true, FlightLevel.DANGER).action())
                .isEqualTo(AlertStateService.Action.TRIGGER);
        assertThat(service.evaluate("key", 1, true, FlightLevel.DANGER).action())
                .isEqualTo(AlertStateService.Action.NONE);
    }

    @Test
    void escalationPublishesImmediately() {
        service.evaluate("key", 1, true, FlightLevel.DANGER);
        assertThat(service.evaluate("key", 1, true, FlightLevel.BAN).action())
                .isEqualTo(AlertStateService.Action.ESCALATE);
    }

    @Test
    void resolutionRequiresTwoConsecutiveSafeRuns() {
        service.evaluate("key", 1, true, FlightLevel.DANGER);
        assertThat(service.evaluate("key", 2, false, FlightLevel.FIT).action())
                .isEqualTo(AlertStateService.Action.NONE);
        assertThat(service.evaluate("key", 3, false, FlightLevel.FIT).action())
                .isEqualTo(AlertStateService.Action.RESOLVE);
    }

    @Test
    void sameRunIsCountedOnlyOnceForRecovery() {
        service.evaluate("key", 1, true, FlightLevel.DANGER);
        assertThat(service.evaluate("key", 2, false, FlightLevel.FIT).action()).isEqualTo(AlertStateService.Action.NONE);
        assertThat(service.evaluate("key", 2, false, FlightLevel.FIT).action()).isEqualTo(AlertStateService.Action.NONE);
        assertThat(service.evaluate("key", 3, false, FlightLevel.FIT).action()).isEqualTo(AlertStateService.Action.RESOLVE);
    }
}
