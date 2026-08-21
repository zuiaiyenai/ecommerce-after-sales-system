package com.ecommerce.aftersales.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ecommerce.aftersales.entity.AfterSalesTicket;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;
import java.time.LocalDateTime;

public interface AfterSalesTicketMapper extends BaseMapper<AfterSalesTicket> {

    @Select("SELECT * FROM after_sales_ticket WHERE id = #{ticketId} AND deleted = 0 FOR UPDATE")
    AfterSalesTicket selectByIdForUpdate(@Param("ticketId") Long ticketId);

    @Update("""
            UPDATE after_sales_ticket
            SET evidence_revision = evidence_revision + 1,
                ai_review_status = 'RESUME_PENDING',
                audit_opinion = #{auditOpinion},
                update_time = #{updateTime}
            WHERE id = #{ticketId}
              AND deleted = 0
              AND ai_review_request_id = #{reviewRequestId}
              AND ai_review_result IS NULL
            """)
    int advanceEvidenceRevision(
            @Param("ticketId") Long ticketId,
            @Param("reviewRequestId") String reviewRequestId,
            @Param("auditOpinion") String auditOpinion,
            @Param("updateTime") LocalDateTime updateTime
    );

    @Update("""
            UPDATE after_sales_ticket
            SET ai_review_status = 'WAITING_EVIDENCE',
                audit_opinion = #{auditOpinion},
                update_time = #{updateTime}
            WHERE id = #{ticketId}
              AND deleted = 0
              AND ai_review_request_id = #{reviewRequestId}
              AND ai_review_result IS NULL
              AND evidence_revision = #{evidenceRevision}
            """)
    int markWaitingEvidenceIfCurrent(
            @Param("ticketId") Long ticketId,
            @Param("reviewRequestId") String reviewRequestId,
            @Param("evidenceRevision") Integer evidenceRevision,
            @Param("auditOpinion") String auditOpinion,
            @Param("updateTime") LocalDateTime updateTime
    );

    @Update("""
            UPDATE after_sales_ticket
            SET ai_review_result = 'APPROVE',
                ai_review_status = 'COMPLETED',
                ai_review_reason = #{reason},
                ai_review_time = #{reviewTime},
                ai_review_audit_json = #{auditPayload},
                ai_review_confidence = #{confidence},
                audit_opinion = #{reason},
                status = 'PROCESSING',
                manual_review_required = 0,
                priority = 0,
                audit_time = #{reviewTime},
                expected_complete_time = #{expectedCompleteTime},
                update_time = #{reviewTime}
            WHERE id = #{ticketId}
              AND deleted = 0
              AND status IN ('PENDING', 'PENDING_REVIEW')
              AND ai_review_request_id = #{reviewRequestId}
              AND ai_review_result IS NULL
              AND evidence_revision = #{evidenceRevision}
            """)
    int applyAiApprovalIfPending(
            @Param("ticketId") Long ticketId,
            @Param("reviewRequestId") String reviewRequestId,
            @Param("evidenceRevision") Integer evidenceRevision,
            @Param("reason") String reason,
            @Param("auditPayload") String auditPayload,
            @Param("confidence") BigDecimal confidence,
            @Param("reviewTime") LocalDateTime reviewTime,
            @Param("expectedCompleteTime") LocalDateTime expectedCompleteTime
    );

    default int applyAiApprovalIfPending(
            Long ticketId, String reviewRequestId, String reason, String auditPayload,
            BigDecimal confidence, LocalDateTime reviewTime, LocalDateTime expectedCompleteTime
    ) {
        return applyAiApprovalIfPending(ticketId, reviewRequestId, 0, reason, auditPayload,
                confidence, reviewTime, expectedCompleteTime);
    }

    @Update("""
            UPDATE after_sales_ticket
            SET ai_review_result = 'MANUAL_REVIEW_REQUIRED',
                ai_review_status = 'MANUAL_REQUIRED',
                ai_review_reason = #{reason},
                ai_review_time = #{reviewTime},
                ai_review_audit_json = COALESCE(#{auditPayload}, ai_review_audit_json),
                ai_review_confidence = COALESCE(#{confidence}, ai_review_confidence),
                audit_opinion = #{reason},
                status = CASE WHEN status = 'PENDING' THEN 'PENDING_REVIEW' ELSE status END,
                manual_review_required = 1,
                priority = 1,
                update_time = #{reviewTime}
            WHERE id = #{ticketId}
              AND deleted = 0
              AND status IN ('PENDING', 'PENDING_REVIEW')
              AND ai_review_request_id = #{reviewRequestId}
              AND ai_review_result IS NULL
              AND (#{evidenceRevision} IS NULL OR evidence_revision = #{evidenceRevision})
            """)
    int applyManualReviewIfPending(
            @Param("ticketId") Long ticketId,
            @Param("reviewRequestId") String reviewRequestId,
            @Param("evidenceRevision") Integer evidenceRevision,
            @Param("reason") String reason,
            @Param("auditPayload") String auditPayload,
            @Param("confidence") BigDecimal confidence,
            @Param("reviewTime") LocalDateTime reviewTime
    );

    default int applyManualReviewIfPending(
            Long ticketId, String reviewRequestId, String reason, String auditPayload,
            BigDecimal confidence, LocalDateTime reviewTime
    ) {
        return applyManualReviewIfPending(ticketId, reviewRequestId, null, reason, auditPayload,
                confidence, reviewTime);
    }
}
