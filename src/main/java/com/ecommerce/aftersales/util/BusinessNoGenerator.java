package com.ecommerce.aftersales.util;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;

public final class BusinessNoGenerator {

    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ofPattern("yyMMdd");

    private BusinessNoGenerator() {
    }

    public static String dailySerial(String prefix, long existingTodayCount) {
        return prefix + LocalDate.now().format(DATE_FORMATTER) + String.format("%04d", existingTodayCount + 1);
    }

    public static String dailyPrefix(String prefix) {
        return prefix + LocalDate.now().format(DATE_FORMATTER);
    }
}
