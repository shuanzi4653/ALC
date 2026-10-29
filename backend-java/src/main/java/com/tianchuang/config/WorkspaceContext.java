package com.tianchuang.config;

import java.util.function.Supplier;
import java.util.regex.Pattern;

public final class WorkspaceContext {

    public static final String HEADER = "X-ALC-Workspace";
    public static final String COOKIE = "alc_ws";
    public static final String QUERY = "ws";
    public static final String UNIDENTIFIED = "";

    private static final Pattern PATTERN = Pattern.compile("^[A-Za-z0-9_-]{6,64}$");

    private static final ThreadLocal<String> CURRENT = ThreadLocal.withInitial(() -> UNIDENTIFIED);

    private WorkspaceContext() {
    }

    public static String normalize(String value) {
        if (value == null) {
            return UNIDENTIFIED;
        }
        String text = value.trim();
        return PATTERN.matcher(text).matches() ? text : UNIDENTIFIED;
    }

    public static String current() {
        return CURRENT.get();
    }

    public static void set(String value) {
        CURRENT.set(normalize(value));
    }

    public static void clear() {
        CURRENT.remove();
    }

    public static <T> T call(String workspace, Supplier<T> body) {
        String previous = current();
        set(workspace);
        try {
            return body.get();
        } finally {
            set(previous);
        }
    }
}
