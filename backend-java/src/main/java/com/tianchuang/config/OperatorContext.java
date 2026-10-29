package com.tianchuang.config;

public final class OperatorContext {

    public static final String HEADER = "X-ALC-Operator";

    private static final ThreadLocal<String> CURRENT = new ThreadLocal<>();

    private OperatorContext() {
    }

    public static void set(String operator) {
        if (operator == null || operator.isBlank()) CURRENT.remove();
        else CURRENT.set(operator.trim());
    }

    public static String current() {
        return CURRENT.get();
    }

    public static void clear() {
        CURRENT.remove();
    }
}
