package com.ecommerce.aftersales.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ecommerce.aftersales.entity.UserFeedback;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.LocalDateTime;

public interface UserFeedbackMapper extends BaseMapper<UserFeedback> {
    @Select("SELECT id FROM user_info WHERE id = #{userId} AND deleted = 0 FOR UPDATE")
    Long lockUserForSubmit(@Param("userId") Long userId);

    @Select("""
            SELECT id, user_id, type, content, contact, status, deleted, create_time, update_time
            FROM user_feedback
            WHERE user_id = #{userId}
              AND type = #{type}
              AND content = #{content}
              AND create_time >= #{createdAfter}
              AND deleted = 0
            ORDER BY create_time DESC
            LIMIT 1
            FOR UPDATE
            """)
    UserFeedback selectRecentDuplicate(@Param("userId") Long userId,
                                       @Param("type") String type,
                                       @Param("content") String content,
                                       @Param("createdAfter") LocalDateTime createdAfter);
}
