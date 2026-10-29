package com.tianchuang.controller;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.web.context.HttpSessionSecurityContextRepository;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {
    private final AuthenticationManager manager;
    private final boolean securityEnabled;
    private final HttpSessionSecurityContextRepository contexts = new HttpSessionSecurityContextRepository();

    public AuthController(AuthenticationManager manager, @Value("${security.enabled:false}") boolean securityEnabled) {
        this.manager = manager;
        this.securityEnabled = securityEnabled;
    }

    public record LoginRequest(String username, String password) {}

    @GetMapping("/status")
    public Map<String, Object> status(Authentication authentication, CsrfToken csrf) {
        if (csrf != null) csrf.getToken();
        boolean signedIn = !securityEnabled || authentication != null
                && authentication.isAuthenticated() && !"anonymousUser".equals(authentication.getPrincipal());
        return Map.of("enabled", securityEnabled, "authenticated", signedIn,
                "username", signedIn && authentication != null ? authentication.getName() : "");
    }

    @PostMapping("/login")
    public Map<String, Object> login(@RequestBody LoginRequest request, HttpServletRequest servletRequest,
                                     HttpServletResponse response) {
        Authentication authentication = manager.authenticate(
                UsernamePasswordAuthenticationToken.unauthenticated(request.username(), request.password()));
        var context = SecurityContextHolder.createEmptyContext();
        context.setAuthentication(authentication);
        SecurityContextHolder.setContext(context);
        contexts.saveContext(context, servletRequest, response);
        return Map.of("authenticated", true, "username", authentication.getName(), "enabled", securityEnabled);
    }
}
