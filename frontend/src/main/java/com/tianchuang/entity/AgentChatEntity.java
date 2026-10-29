package com.tianchuang.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

/**
 * 智能体问答历史
 *
 * <p>{@code workspace} = 提问者所属的工作区（2026-10-14 随拆登录门引入）。存的是
 * <b>用户自己提的问题</b>，所以必须能分辨归属；空串 = 「未标识」（与
 * {@code WorkspaceContext.UNIDENTIFIED}、Python {@code workspace.py::UNIDENTIFIED}
 * 同一个字面量）。库侧列由 Flyway {@code V5__workspace_scope.sql} 补。</p>
 */
@Entity
@Table(name = "agent_chat")
public class AgentChatEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    public Long id;

    public LocalDateTime ts = LocalDateTime.now();
    @Lob
    public String question;
    @Lob
    public String answer;
    public String source;        // deepseek | fallback
    public int latencyMs;
    @Column(length = 64, nullable = false)
    public String workspace = "";
}
