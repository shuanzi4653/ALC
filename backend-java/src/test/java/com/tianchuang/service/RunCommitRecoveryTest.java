package com.tianchuang.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tianchuang.entity.MonitoringRunEntity;
import com.tianchuang.entity.Track2JobEntity;
import com.tianchuang.entity.TrackResultEntity;
import com.tianchuang.repository.MonitoringRunRepo;
import com.tianchuang.repository.SfiRecordRepo;
import com.tianchuang.repository.Track2JobRepo;
import com.tianchuang.repository.TrackResultRepo;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class RunCommitRecoveryTest {
    @Test
    void restartConvergesJobTrackAndRunTogether() {
        MonitoringRunRepo runs = mock(MonitoringRunRepo.class);
        TrackResultRepo tracks = mock(TrackResultRepo.class);
        Track2JobRepo jobs = mock(Track2JobRepo.class);
        Track2JobEntity job = new Track2JobEntity();
        job.runId = "run-1"; job.status = "RUNNING"; job.dueAt = LocalDateTime.now().plusSeconds(10);
        TrackResultEntity track = new TrackResultEntity(); track.runId = "run-1"; track.status = "PENDING";
        MonitoringRunEntity run = new MonitoringRunEntity(); run.runId = "run-1"; run.status = "RULE_READY"; run.revision = 1;
        when(jobs.findByStatusIn(any())).thenReturn(List.of(job));
        when(tracks.findFirstByRunIdOrderByRevisionDesc("run-1")).thenReturn(Optional.of(track));
        when(runs.findByRunId("run-1")).thenReturn(Optional.of(run));
        RunCommitService service = new RunCommitService(runs, mock(SfiRecordRepo.class), tracks, jobs, new ObjectMapper());

        assertThat(service.expireUnfinishedJobs("JVM_RESTART")).isEqualTo(1);
        assertThat(job.status).isEqualTo("FAILED");
        assertThat(track.status).isEqualTo("UNAVAILABLE");
        assertThat(track.revision).isEqualTo(2);
        assertThat(run.status).isEqualTo("COMPLETE");
        assertThat(run.revision).isEqualTo(2);
    }
}
