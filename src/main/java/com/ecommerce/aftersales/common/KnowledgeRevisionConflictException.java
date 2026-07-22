package com.ecommerce.aftersales.common;

import lombok.Getter;

@Getter
public final class KnowledgeRevisionConflictException extends RuntimeException {
    private final long currentRevision;
    private final String reviewStatus;

    public KnowledgeRevisionConflictException(long currentRevision, String reviewStatus) {
        super("知识已被其他操作更新，请刷新后重试");
        this.currentRevision = currentRevision;
        this.reviewStatus = reviewStatus;
    }
}
