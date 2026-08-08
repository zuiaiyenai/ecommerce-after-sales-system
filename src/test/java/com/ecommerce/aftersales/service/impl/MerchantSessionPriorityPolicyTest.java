package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.dto.MerchantCsDtos.MessageView;
import com.ecommerce.aftersales.dto.MerchantCsDtos.SessionView;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class MerchantSessionPriorityPolicyTest {

    @Test
    void userLastMessageMeansUnreplied() {
        String sender = MerchantSessionPriorityPolicy.normalizeSender("USER");

        String status = MerchantSessionPriorityPolicy.replyStatus(sender);

        assertThat(status).isEqualTo(MerchantSessionPriorityPolicy.REPLY_STATUS_UNREPLIED);
    }

    @Test
    void serviceLastMessageMeansReplied() {
        String sender = MerchantSessionPriorityPolicy.normalizeSender("SERVICE");

        String status = MerchantSessionPriorityPolicy.replyStatus(sender);

        assertThat(status).isEqualTo(MerchantSessionPriorityPolicy.REPLY_STATUS_REPLIED);
    }

    @Test
    void assistantLastMessageDoesNotMeanStaffReplied() {
        String sender = MerchantSessionPriorityPolicy.normalizeSender("ASSISTANT");

        String status = MerchantSessionPriorityPolicy.replyStatus(sender);

        assertThat(sender).isEqualTo("ASSISTANT");
        assertThat(status).isEqualTo(MerchantSessionPriorityPolicy.REPLY_STATUS_UNREPLIED);
    }

    @Test
    void systemLastMessageDoesNotMeanStaffReplied() {
        String sender = MerchantSessionPriorityPolicy.normalizeSender("SYSTEM");

        assertThat(sender).isEqualTo("SYSTEM");
        assertThat(MerchantSessionPriorityPolicy.replyStatus(sender))
                .isEqualTo(MerchantSessionPriorityPolicy.REPLY_STATUS_UNREPLIED);
    }

    @Test
    void repliedSessionDoesNotAccumulateWaitingTime() {
        LocalDateTime now = LocalDateTime.of(2026, 7, 14, 1, 0);
        int withOldMessage = MerchantSessionPriorityPolicy.priorityScore(
                MerchantSessionPriorityPolicy.REPLY_STATUS_REPLIED,
                BigDecimal.ZERO,
                now.minusMinutes(120),
                now
        );

        assertThat(withOldMessage).isZero();
    }

    @Test
    void imageMessageViewCarriesFileUrl() {
        MessageView message = new MessageView();
        message.setMessageId(1L);
        message.setSender("USER");
        message.setMessageType("IMAGE");
        message.setContent("[图片]");
        message.setFileUrl("/uploads/chat/demo.jpg");

        assertThat(message.getMessageType()).isEqualTo("IMAGE");
        assertThat(message.getFileUrl()).isEqualTo("/uploads/chat/demo.jpg");
    }

    @Test
    void unrepliedWaitingSessionRanksBeforeRepliedHighEmotionSession() {
        LocalDateTime now = LocalDateTime.of(2026, 7, 14, 1, 0);
        SessionView a = new SessionView();
        a.setSessionId(1L);
        a.setReplyStatus(MerchantSessionPriorityPolicy.REPLY_STATUS_UNREPLIED);
        a.setEmotionScore(new BigDecimal("0.80"));
        a.setLastMessageTime("2026-07-14 00:00:00");
        a.setPriorityScore(MerchantSessionPriorityPolicy.priorityScore(
                a.getReplyStatus(),
                a.getEmotionScore(),
                now.minusMinutes(60),
                now
        ));

        SessionView b = new SessionView();
        b.setSessionId(2L);
        b.setReplyStatus(MerchantSessionPriorityPolicy.REPLY_STATUS_REPLIED);
        b.setEmotionScore(new BigDecimal("0.95"));
        b.setLastMessageTime("2026-07-14 00:59:00");
        b.setPriorityScore(MerchantSessionPriorityPolicy.priorityScore(
                b.getReplyStatus(),
                b.getEmotionScore(),
                now.minusMinutes(1),
                now
        ));

        List<SessionView> sorted = List.of(b, a).stream()
                .sorted(MerchantSessionPriorityPolicy.sessionComparator())
                .toList();

        assertThat(sorted).containsExactly(a, b);
    }

    @Test
    void risingEmotionScoresProduceUpTrend() {
        String trend = MerchantSessionPriorityPolicy.emotionTrend(List.of(
                new BigDecimal("0.30"),
                new BigDecimal("0.70"),
                new BigDecimal("0.90")
        ));

        assertThat(trend).isEqualTo(MerchantSessionPriorityPolicy.TREND_UP);
    }
}
