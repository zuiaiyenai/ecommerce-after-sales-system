package com.ecommerce.aftersales.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.entity.MessageNotice;
import com.ecommerce.aftersales.mapper.MessageNoticeMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@RequiredArgsConstructor
public class NotificationService {

    private final MessageNoticeMapper messageNoticeMapper;

    @Transactional(rollbackFor = Exception.class)
    public void createNotification(Long userId, String title, String content,
                                   String noticeType, Long refId, String refType) {
        if (userId == null) {
            return;
        }
        MessageNotice notice = new MessageNotice();
        notice.setUserId(userId);
        notice.setTitle(title);
        notice.setContent(content);
        notice.setNoticeType(noticeType);
        notice.setRefId(refId);
        notice.setRefType(refType);
        notice.setIsRead(0);
        messageNoticeMapper.insert(notice);
    }

    public long countUnread(Long userId) {
        return messageNoticeMapper.selectCount(
                new LambdaQueryWrapper<MessageNotice>()
                        .eq(MessageNotice::getUserId, userId)
                        .eq(MessageNotice::getIsRead, 0)
        );
    }
}
