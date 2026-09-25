package com.ecommerce.aftersales.service.impl;

import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.dto.UserFeedbackDtos;
import com.ecommerce.aftersales.entity.SysUser;
import com.ecommerce.aftersales.entity.UserFeedback;
import com.ecommerce.aftersales.mapper.SysUserMapper;
import com.ecommerce.aftersales.mapper.UserFeedbackMapper;
import org.junit.jupiter.api.Test;

import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class UserFeedbackServiceImplTest {

    @Test
    void submitsTrimmedFeedbackForAuthenticatedUser() {
        UserFeedbackMapper mapper = mock(UserFeedbackMapper.class);
        when(mapper.lockUserForSubmit(7L)).thenReturn(7L);
        when(mapper.selectRecentDuplicate(any(), any(), any(), any())).thenReturn(null);
        doAnswer(invocation -> {
            UserFeedback inserted = invocation.getArgument(0);
            inserted.setId(21L);
            inserted.setCreateTime(LocalDateTime.now());
            return 1;
        }).when(mapper).insert(any(UserFeedback.class));
        UserFeedbackServiceImpl service = new UserFeedbackServiceImpl(mapper, mock(SysUserMapper.class));

        var result = service.submit(7L, request("  希望增加处理进度提醒  "));

        assertThat(result.getId()).isEqualTo(21L);
        assertThat(result.getUserId()).isEqualTo(7L);
        assertThat(result.getContent()).isEqualTo("希望增加处理进度提醒");
        assertThat(result.getStatus()).isEqualTo("PENDING");
    }

    @Test
    void rejectsSameFeedbackSubmittedWithinOneMinute() {
        UserFeedbackMapper mapper = mock(UserFeedbackMapper.class);
        when(mapper.lockUserForSubmit(7L)).thenReturn(7L);
        when(mapper.selectRecentDuplicate(any(), any(), any(), any())).thenReturn(new UserFeedback());
        UserFeedbackServiceImpl service = new UserFeedbackServiceImpl(mapper, mock(SysUserMapper.class));

        assertThatThrownBy(() -> service.submit(7L, request("希望增加处理进度提醒")))
                .isInstanceOf(BizException.class)
                .extracting("code")
                .isEqualTo(409);
        verify(mapper, never()).insert(any(UserFeedback.class));
    }

    @Test
    void rejectsFeedbackWhenAuthenticatedUserNoLongerExists() {
        UserFeedbackMapper mapper = mock(UserFeedbackMapper.class);
        when(mapper.lockUserForSubmit(7L)).thenReturn(null);
        UserFeedbackServiceImpl service = new UserFeedbackServiceImpl(mapper, mock(SysUserMapper.class));

        assertThatThrownBy(() -> service.submit(7L, request("希望增加处理进度提醒")))
                .isInstanceOf(BizException.class)
                .extracting("code")
                .isEqualTo(401);
        verify(mapper, never()).insert(any(UserFeedback.class));
    }

    @Test
    void allowsOnlyEnabledAdminToQueryFeedback() {
        UserFeedbackMapper mapper = mock(UserFeedbackMapper.class);
        SysUserMapper sysUserMapper = mock(SysUserMapper.class);
        SysUser normalUser = new SysUser();
        normalUser.setRoleType("AGENT");
        normalUser.setStatus(1);
        when(sysUserMapper.selectById(3L)).thenReturn(normalUser);
        UserFeedbackServiceImpl service = new UserFeedbackServiceImpl(mapper, sysUserMapper);

        assertThatThrownBy(() -> service.listForAdmin(3L, 1, 20, null, null))
                .isInstanceOf(BizException.class)
                .extracting("code")
                .isEqualTo(403);
        verify(mapper, never()).selectList(any());
    }

    @Test
    void returnsPagedFeedbackToAdmin() {
        UserFeedbackMapper mapper = mock(UserFeedbackMapper.class);
        SysUserMapper sysUserMapper = mock(SysUserMapper.class);
        SysUser admin = new SysUser();
        admin.setRoleType("ADMIN");
        admin.setStatus(1);
        when(sysUserMapper.selectById(3L)).thenReturn(admin);
        UserFeedback feedback = new UserFeedback();
        feedback.setId(21L);
        feedback.setUserId(7L);
        feedback.setType("FUNCTION");
        feedback.setContent("希望增加处理进度提醒");
        feedback.setStatus("PENDING");
        when(mapper.selectList(any())).thenReturn(List.of(feedback));
        UserFeedbackServiceImpl service = new UserFeedbackServiceImpl(mapper, sysUserMapper);

        var page = service.listForAdmin(3L, 1, 20, "pending", "function");

        assertThat(page.getRecords()).hasSize(1);
        assertThat(page.getTotal()).isEqualTo(1);
        assertThat(page.getRecords().getFirst().getId()).isEqualTo(21L);
    }

    private static UserFeedbackDtos.SubmitRequest request(String content) {
        UserFeedbackDtos.SubmitRequest request = new UserFeedbackDtos.SubmitRequest();
        request.setType("FUNCTION");
        request.setContent(content);
        request.setContact("13991000001");
        return request;
    }
}
