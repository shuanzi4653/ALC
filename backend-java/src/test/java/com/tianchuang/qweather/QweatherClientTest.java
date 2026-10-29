package com.tianchuang.qweather;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.zip.GZIPOutputStream;

import org.junit.jupiter.api.Test;

/** 和风坐标合同：URL 拼装与坐标校验都不依赖网络。 */
class QweatherClientTest {

    private static byte[] gzip(String text) throws Exception {
        ByteArrayOutputStream buffer = new ByteArrayOutputStream();
        try (GZIPOutputStream out = new GZIPOutputStream(buffer)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        }
        return buffer.toByteArray();
    }

    @Test
    void gzippedBodiesAreDecodedBeforeJacksonSeesThem() throws Exception {
        String json = "{\"code\":\"200\",\"now\":{\"temp\":\"18\"}}";
        byte[] encoded = gzip(json);
        // The compressed body starts with the gzip magic 1F 8B, which is exactly what
        // made Jackson raise "Illegal character (CTRL-CHAR, code 31)" in production.
        assertEquals(0x1F, encoded[0] & 0xFF);
        assertEquals(0x8B, encoded[1] & 0xFF);
        assertArrayEquals(json.getBytes(StandardCharsets.UTF_8),
                QweatherClient.decodeBody(encoded, "gzip"));
    }

    @Test
    void plainAndEmptyBodiesPassThroughUntouched() throws Exception {
        String json = "{\"code\":\"200\"}";
        byte[] plain = json.getBytes(StandardCharsets.UTF_8);
        assertArrayEquals(plain, QweatherClient.decodeBody(plain, ""));
        assertArrayEquals(plain, QweatherClient.decodeBody(plain, null));
        assertArrayEquals(new byte[0], QweatherClient.decodeBody(null, "gzip"));
        assertArrayEquals(new byte[] {0x7B}, QweatherClient.decodeBody(new byte[] {0x7B}, "gzip"));
    }

    @Test
    void currentUrlCarriesExplicitCoordinates() {
        assertEquals("https://api.example.com/weather/v1/current/41.8/123.43?localTime=true&lang=zh",
                QweatherClient.currentUrl("api.example.com", 41.8, 123.43));
    }

    @Test
    void hourlyUrlCarriesHoursAndCoordinates() {
        String url = QweatherClient.hourlyUrl("api.example.com", 24, 45.75, 126.65);
        assertTrue(url.startsWith("https://api.example.com/weather/v1/hourly/45.75/126.65?"), url);
        assertTrue(url.contains("hours=24"), url);
    }

    @Test
    void coordinatesOutsideTheLegalRangeAreRejected() {
        assertThrows(IllegalArgumentException.class, () -> QweatherClient.checkCoordinate(91.0, 120.0));
        assertThrows(IllegalArgumentException.class, () -> QweatherClient.checkCoordinate(45.0, 181.0));
        assertThrows(IllegalArgumentException.class, () -> QweatherClient.checkCoordinate(Double.NaN, 120.0));
        assertThrows(IllegalArgumentException.class,
                () -> QweatherClient.checkCoordinate(45.0, Double.POSITIVE_INFINITY));
    }

    @Test
    void northeastCoordinatesAreAcceptedAndNotSnapped() {
        QweatherClient.checkCoordinate(52.33, 124.71);
        QweatherClient.checkCoordinate(43.11, 131.31);
        assertEquals("https://api.example.com/weather/v1/current/52.33/124.71?localTime=true&lang=zh",
                QweatherClient.currentUrl("api.example.com", 52.33, 124.71));
    }
}
