package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.dto.UserFeedbackDtos;
import com.ecommerce.aftersales.entity.SysUser;
import com.ecommerce.aftersales.entity.UserFeedback;
import com.ecommerce.aftersales.mapper.SysUserMapper;
import com.ecommerce.aftersales.mapper.UserFeedbackMapper;
import com.ecommerce.aftersales.service.UserFeedbackService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class UserFeedbackServiceImpl implements UserFeedbackService {
    private static final int MAX_PAGE_SIZE = 100;

    private final UserFeedbackMapper userFeedbackMapper;
    private final SysUserMapper sysUserMapper;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public UserFeedbackDtos.Response submit(Long userId, UserFeedbackDtos.SubmitRequest request) {
        String type = request.getType().trim().toUpperCase();
        String content = request.getContent().trim();
        if (userFeedbackMapper.lockUserForSubmit(userId) == null) {
            throw new BizException(401, "用户不存在或已失效");
        }
        UserFeedback duplicate = userFeedbackMapper.selectRecentDuplicate(
                userId, type, content, LocalDateTime.now().minusMinutes(1));
        if (duplicate != null) {
            throw new BizException(409, "请勿重复提交相同反馈");
        }

        UserFeedback feedback = new UserFeedback();
        feedback.setUserId(userId);
        feedback.setType(type);
        feedback.setContent(content);
        feedback.setContact(blankToNull(request.getContact()));
        feedback.setStatus("PENDING");
        feedback.setDeleted(0);
        userFeedbackMapper.insert(feedback);
        return toResponse(feedback);
    }

    @Override
    public PageResult<UserFeedbackDtos.Response> listForAdmin(Long adminId, long page, long size,
                                                              String status, String type) {
        requireAdmin(adminId);
        LambdaQueryWrapper<UserFeedback> query = new LambdaQueryWrapper<UserFeedback>()
                .eq(StringUtils.hasText(status), UserFeedback::getStatus, normalize(status))
                .eq(StringUtils.hasText(type), UserFeedback::getType, normalize(type))
                .orderByDesc(UserFeedback::getCreateTime);
        List<UserFeedbackDtos.Response> records = userFeedbackMapper.selectList(query).stream()
                .map(UserFeedbackServiceImpl::toResponse)
                .toList();
        return PageResult.of(records, page, Math.min(Math.max(size, 1), MAX_PAGE_SIZE));
    }

    private void requireAdmin(Long adminId) {
        SysUser admin = sysUserMapper.selectById(adminId);
        if (admin == null || !"ADMIN".equalsIgnoreCase(admin.getRoleType())) {
            throw new BizException(403, "当前账号没有管理员权限");
        }
        if (!Integer.valueOf(1).equals(admin.getStatus())) {
            throw new BizException(403, "管理员账号已被禁用");
        }
    }

    private static String normalize(String value) {
        return value == null ? null : value.trim().toUpperCase();
    }

    private static String blankToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private static UserFeedbackDtos.Response toResponse(UserFeedback feedback) {
        return UserFeedbackDtos.Response.builder()
                .id(feedback.getId())
                .userId(feedback.getUserId())
                .type(feedback.getType())
                .content(feedback.getContent())
                .contact(feedback.getContact())
                .status(feedback.getStatus())
                .createTime(feedback.getCreateTime())
                .updateTime(feedback.getUpdateTime())
                .build();
    }
}
