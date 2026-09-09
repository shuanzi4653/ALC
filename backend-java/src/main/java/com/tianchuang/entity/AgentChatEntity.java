package com.tianchuang.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;

import java.time.LocalDateTime;

/** 智能体问答历史 */
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
}
