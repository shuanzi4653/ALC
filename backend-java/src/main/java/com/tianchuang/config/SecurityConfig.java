package com.tianchuang.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.authentication.AuthenticationManager;
import org.springframework.security.config.annotation.authentication.configuration.AuthenticationConfiguration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.csrf.CookieCsrfTokenRepository;

@Configuration
public class SecurityConfig {
    private static final Logger log = LoggerFactory.getLogger(SecurityConfig.class);

    @Bean
    @ConditionalOnProperty(name = "security.enabled", havingValue = "false", matchIfMissing = true)
    SecurityFilterChain permitAllChain(HttpSecurity http) throws Exception {
        log.info("权限关闭：本机演示模式");
        http.csrf(csrf -> csrf.disable())
            .logout(logout -> logout.disable())
            .headers(headers -> headers.cacheControl(cache -> cache.disable()))
            .authorizeHttpRequests(auth -> auth.anyRequest().permitAll());
        return http.build();
    }

    @Bean
    @ConditionalOnProperty(name = "security.enabled", havingValue = "true")
    SecurityFilterChain securedChain(HttpSecurity http, ObjectMapper mapper) throws Exception {
        CookieCsrfTokenRepository csrf = CookieCsrfTokenRepository.withHttpOnlyFalse();
        http.csrf(config -> config.csrfTokenRepository(csrf)
                    .ignoringRequestMatchers("/api/auth/login"))
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.IF_REQUIRED))
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/", "/index.html", "/assets/**", "/favicon.ico",
                        "/api/health/**", "/api/auth/**", "/actuator/health/**").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/internal/qweather/**").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/**").hasAnyRole("VIEWER", "OPERATOR", "ADMIN")
                .requestMatchers("/ws/**").authenticated()
                .requestMatchers(HttpMethod.POST, "/api/monitor/**", "/api/sim/**").hasAnyRole("OPERATOR", "ADMIN")
                .requestMatchers(HttpMethod.POST, "/api/**").hasRole("ADMIN")
                .anyRequest().denyAll())
            .exceptionHandling(errors -> errors
                .authenticationEntryPoint((request, response, exception) -> jsonError(mapper, response, 401, "AUTH_REQUIRED", "请先登录"))
                .accessDeniedHandler((request, response, exception) -> jsonError(mapper, response, 403, "ACCESS_DENIED", "当前账号无权执行该操作")));
        return http.build();
    }

    private static void jsonError(ObjectMapper mapper, HttpServletResponse response, int status,
                                  String code, String message) throws java.io.IOException {
        response.setStatus(status);
        response.setContentType("application/json;charset=UTF-8");
        mapper.writeValue(response.getWriter(), Map.of("code", code, "message", message, "retryable", false));
    }

    @Bean PasswordEncoder passwordEncoder() { return new BCryptPasswordEncoder(); }
    @Bean AuthenticationManager authenticationManager(AuthenticationConfiguration configuration) throws Exception {
        return configuration.getAuthenticationManager();
    }

    @Bean
    UserDetailsService userDetailsService(
            @Value("${security.viewer-user:}") String viewerUser,
            @Value("${security.viewer-password:}") String viewerPassword,
            @Value("${security.operator-user:}") String operatorUser,
            @Value("${security.operator-password:}") String operatorPassword,
            @Value("${security.admin-user:}") String adminUser,
            @Value("${security.admin-password:}") String adminPassword,
            @Value("${security.allow-demo-user:true}") boolean allowDemoUser,
            @Value("${security.enabled:false}") boolean enabled,
            PasswordEncoder encoder) {
        List<UserDetails> users = new ArrayList<>();
        addUser(users, viewerUser, viewerPassword, "VIEWER", encoder);
        addUser(users, operatorUser, operatorPassword, "OPERATOR", encoder);
        addUser(users, adminUser, adminPassword, "ADMIN", encoder);
        if (users.isEmpty() && enabled && !allowDemoUser) {
            throw new IllegalStateException("权限已启用，但未配置任何账号；受控环境拒绝使用固定演示账号");
        }
        if (users.isEmpty()) {
            log.warn("使用本机演示账号 viewer/viewer-demo；受控环境请设置 security.allow-demo-user=false");
            users.add(User.withUsername("viewer").password(encoder.encode("viewer-demo")).roles("VIEWER").build());
        }
        return new InMemoryUserDetailsManager(users);
    }

    private void addUser(List<UserDetails> users, String name, String password, String role, PasswordEncoder encoder) {
        if (name != null && !name.isBlank() && password != null && !password.isBlank()) {
            users.add(User.withUsername(name).password(encoder.encode(password)).roles(role).build());
        }
    }
}
