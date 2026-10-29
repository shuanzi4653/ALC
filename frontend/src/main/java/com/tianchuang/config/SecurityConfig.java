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

/** 可切换的本机演示与受控部署权限边界。 */
@Configuration
public class SecurityConfig {
    private static final Logger log = LoggerFactory.getLogger(SecurityConfig.class);

    @Bean
    @ConditionalOnProperty(name = "security.enabled", havingValue = "false", matchIfMissing = true)
    SecurityFilterChain permitAllChain(HttpSecurity http) throws Exception {
        log.info("权限关闭：本机演示模式");
        // ⚠️ logout() 必须显式关掉。Spring Security 默认会注册 LogoutFilter，
        //    它的默认成功地址是 `/login` —— 而 2026-10-14 登录门拆除后**那个页面
        //    已经不存在**。于是 `GET /logout` 会 302 到一个死页：功能拆了、指向它的
        //    跳转还在，正是「半拆」的典型形态（浏览器表现为"被送去一个 404"）。
        //    关掉之后该路径不再被拦截，落回普通路由（404），也就没有死跳转了。
        // 0.11.6（E-1⑤）：关掉默认的 `Cache-Control: no-store`。
        //
        // Spring Security 默认给**每个**响应加 `no-store, max-age=0`。这条默认值在
        // 有会话的系统里是对的，但本系统 2026-10-14 已拆除登录门、响应里没有任何
        // 凭据 —— 它的唯一效果是**让 E-1⑤ 的 ETag/304 永远无法生效**：
        // 浏览器不存响应，就不会在下次请求里带 If-None-Match。
        // 关掉之后由 controller 自己决定（`/traffic/session` 会带 ETag 与 max-age=600）。
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
                // 内部原始天气接口不返回密钥，但由控制器自身限制为“仅本机回环或内部令牌”，
                // 因此不纳入会话角色校验，避免 Python 侧需要伪造前端登录态。
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
