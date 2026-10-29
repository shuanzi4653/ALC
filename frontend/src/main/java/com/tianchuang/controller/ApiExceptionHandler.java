package com.tianchuang.controller;

import com.tianchuang.service.MonitorService.ExternalDataUnavailableException;
import com.tianchuang.service.MonitorService.RunBusyException;
import com.tianchuang.service.LayerService.ResourceNotFoundException;
import com.tianchuang.service.LayerService.LayerVersionConflictException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.security.core.AuthenticationException;

@RestControllerAdvice
public class ApiExceptionHandler {
    @ExceptionHandler(ResourceNotFoundException.class)
    public ResponseEntity<Map<String, Object>> notFound(ResourceNotFoundException e) {
        return error(HttpStatus.NOT_FOUND, "RESOURCE_NOT_FOUND", e.getMessage(), false);
    }

    @ExceptionHandler(LayerVersionConflictException.class)
    public ResponseEntity<Map<String, Object>> layerConflict(LayerVersionConflictException e) {
        return error(HttpStatus.CONFLICT, "LAYER_REVISION_CONFLICT", e.getMessage(), true);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, Object>> badRequest(IllegalArgumentException e) {
        return error(HttpStatus.BAD_REQUEST, "INVALID_INPUT", e.getMessage(), false);
    }

    @ExceptionHandler(RunBusyException.class)
    public ResponseEntity<Map<String, Object>> busy(RunBusyException e) {
        return error(HttpStatus.CONFLICT, "RUN_IN_PROGRESS", e.getMessage(), true);
    }

    @ExceptionHandler(AuthenticationException.class)
    public ResponseEntity<Map<String, Object>> authentication(AuthenticationException e) {
        return error(HttpStatus.UNAUTHORIZED, "INVALID_CREDENTIALS", "用户名或密码错误", false);
    }

    @ExceptionHandler(ExternalDataUnavailableException.class)
    public ResponseEntity<Map<String, Object>> unavailable(ExternalDataUnavailableException e) {
        return error(HttpStatus.SERVICE_UNAVAILABLE, "LIVE_SOURCE_UNAVAILABLE", e.getMessage(), true);
    }

    private ResponseEntity<Map<String, Object>> error(HttpStatus status, String code,
                                                       String message, boolean retryable) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", code);
        body.put("message", message == null ? status.getReasonPhrase() : message);
        body.put("requestId", UUID.randomUUID().toString());
        body.put("runId", null);
        body.put("retryable", retryable);
        return ResponseEntity.status(status).body(body);
    }
}
