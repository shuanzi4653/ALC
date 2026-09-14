package com.tianchuang.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/**
 * 轨2任务启动恢复（C01）。
 * 内存队列不跨进程存活：上次退出时仍为 PENDING/RUNNING 的任务在本次启动即收敛为失败，
 * 避免任务永远停留在「进行中」而无法解释。
 */
@Component
public class Track2JobRecovery {

    private static final Logger log = LoggerFactory.getLogger(Track2JobRecovery.class);

    private final RunCommitService commits;

    public Track2JobRecovery(RunCommitService commits) {
        this.commits = commits;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void recoverUnfinishedJobs() {
        try {
            int expired = commits.expireUnfinishedJobs("JVM_RESTART");
            if (expired > 0) {
                log.warn("启动恢复：{} 个未完成的轨2任务已标记为失败（JVM_RESTART）", expired);
            } else {
                log.info("启动恢复：没有未收敛的轨2任务");
            }
        } catch (Exception e) {
            log.warn("轨2任务启动恢复失败：{}", e.getMessage());
        }
    }
}
