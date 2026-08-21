package com.ecommerce.aftersales.common;

import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.util.Collections;
import java.util.List;

@Data
@NoArgsConstructor
@AllArgsConstructor
public class PageResult<T> {

    private List<T> records;
    private long total;
    private long page;
    private long size;

    public static <T> PageResult<T> of(List<T> records, long page, long size) {
        long safePage = Math.max(page, 1);
        long safeSize = Math.max(size, 1);
        int from = (int) Math.min((safePage - 1) * safeSize, records.size());
        int to = (int) Math.min(from + safeSize, records.size());
        return new PageResult<>(Collections.unmodifiableList(records.subList(from, to)), records.size(), safePage, safeSize);
    }

    /**
     * Creates a page result when the database has already applied LIMIT/OFFSET.
     */
    public static <T> PageResult<T> ofPage(List<T> records, long total, long page, long size) {
        long safePage = Math.max(page, 1);
        long safeSize = Math.max(size, 1);
        List<T> safeRecords = records == null ? List.of() : records;
        return new PageResult<>(Collections.unmodifiableList(safeRecords), Math.max(total, 0), safePage, safeSize);
    }
}
