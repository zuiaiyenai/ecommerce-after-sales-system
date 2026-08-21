package com.ecommerce.aftersales.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ecommerce.aftersales.entity.ChatMessage;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.Collection;
import java.util.List;

public interface ChatMessageMapper extends BaseMapper<ChatMessage> {

    @Select("""
            <script>
            SELECT id, session_id, role, content, message_type, file_url, create_time
            FROM (
                SELECT id, session_id, role, content, message_type, file_url, create_time,
                       ROW_NUMBER() OVER (
                           PARTITION BY session_id
                           ORDER BY create_time DESC, id DESC
                       ) AS row_num
                FROM chat_message
                WHERE session_id IN
                <foreach collection="sessionIds" item="sessionId" open="(" separator="," close=")">
                    #{sessionId}
                </foreach>
            ) ranked
            WHERE row_num = 1
            </script>
            """)
    List<ChatMessage> selectLatestBySessionIds(@Param("sessionIds") Collection<Long> sessionIds);

    @Select("""
            <script>
            SELECT id, session_id, emotion_score, create_time
            FROM (
                SELECT id, session_id, emotion_score, create_time,
                       ROW_NUMBER() OVER (
                           PARTITION BY session_id
                           ORDER BY create_time DESC, id DESC
                       ) AS row_num
                FROM chat_message
                WHERE role = 'USER'
                  AND emotion_score IS NOT NULL
                  AND session_id IN
                <foreach collection="sessionIds" item="sessionId" open="(" separator="," close=")">
                    #{sessionId}
                </foreach>
            ) ranked
            WHERE row_num &lt;= 20
            ORDER BY session_id, create_time, id
            </script>
            """)
    List<ChatMessage> selectRecentUserEmotionsBySessionIds(@Param("sessionIds") Collection<Long> sessionIds);
}
