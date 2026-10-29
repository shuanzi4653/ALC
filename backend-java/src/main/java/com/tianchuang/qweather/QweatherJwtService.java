package com.tianchuang.qweather;

import com.tianchuang.config.QweatherProperties;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.spec.PKCS8EncodedKeySpec;
import java.time.Instant;
import java.util.Base64;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

@Service
public class QweatherJwtService {

    private static final Logger log = LoggerFactory.getLogger(QweatherJwtService.class);
    private static final long TTL_SECONDS = 900;
    private static final long CLOCK_SKEW = 30;

    private final QweatherProperties props;
    private volatile PrivateKey privateKey;
    private volatile String cachedJwt;
    private volatile long cachedExpAt;

    public QweatherJwtService(QweatherProperties props) {
        this.props = props;
    }

    public synchronized String bearerToken() {
        long now = Instant.now().getEpochSecond();
        if (cachedJwt != null && now < cachedExpAt - 60) {
            return cachedJwt;
        }
        cachedJwt = sign(now);
        cachedExpAt = now - CLOCK_SKEW + TTL_SECONDS;
        return cachedJwt;
    }

    private String sign(long nowEpoch) {
        try {
            PrivateKey key = loadPrivateKey();
            String header = "{\"alg\":\"EdDSA\",\"kid\":\"" + props.kid() + "\"}";
            long iat = nowEpoch - CLOCK_SKEW;
            long exp = iat + TTL_SECONDS;
            String payload = "{\"iss\":\"" + props.iss() + "\",\"sub\":\"" + props.sub()
                    + "\",\"iat\":" + iat + ",\"exp\":" + exp + "}";

            String headB64 = Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(header.getBytes(StandardCharsets.UTF_8));
            String payloadB64 = Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(payload.getBytes(StandardCharsets.UTF_8));
            String data = headB64 + "." + payloadB64;

            Signature sig = Signature.getInstance("Ed25519");
            sig.initSign(key);
            sig.update(data.getBytes(StandardCharsets.UTF_8));
            String sigB64 = Base64.getUrlEncoder().withoutPadding().encodeToString(sig.sign());
            return data + "." + sigB64;
        } catch (Exception e) {
            throw new IllegalStateException("和风 JWT 签发失败: " + e.getMessage(), e);
        }
    }

    private PrivateKey loadPrivateKey() throws Exception {
        if (privateKey != null) {
            return privateKey;
        }
        Path path = Path.of(props.privateKeyPath());
        String pem = Files.readString(path);
        pem = pem.replace("-----BEGIN PRIVATE KEY-----", "")
                 .replace("-----END PRIVATE KEY-----", "")
                 .replaceAll("\\s", "");
        byte[] der = Base64.getMimeDecoder().decode(pem);
        KeyFactory kf = KeyFactory.getInstance("Ed25519");
        privateKey = kf.generatePrivate(new PKCS8EncodedKeySpec(der));
        log.info("和风 Ed25519 私钥加载成功: {}", path.toAbsolutePath());
        return privateKey;
    }
}
