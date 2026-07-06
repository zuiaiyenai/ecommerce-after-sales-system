package com.ecommerce.aftersales.config;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.entity.User;
import com.ecommerce.aftersales.mapper.UserMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.util.StringUtils;

@Slf4j
@Configuration
@RequiredArgsConstructor
public class DemoMiniappUserInitializer {

    private static final int USER_STATUS_NORMAL = 1;
    private static final int BIND_STATUS_UNBOUND = 0;
    private static final String ROLE_TYPE_USER = "USER";

    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;
    private final MiniappClientProperties properties;

    @Bean
    public ApplicationRunner ensureDemoMiniappUser() {
        return args -> {
            try {
                MiniappClientProperties.DemoUser demoUser = properties.getDemoUser();
                if (demoUser == null || !Boolean.TRUE.equals(demoUser.getEnabled()) || !StringUtils.hasText(demoUser.getPhone())) {
                    return;
                }
                User existing = userMapper.selectOne(new LambdaQueryWrapper<User>()
                        .eq(User::getPhone, demoUser.getPhone())
                        .last("limit 1"));
                if (existing != null) {
                    return;
                }

                User user = new User();
                user.setUserAccount(demoUser.getPhone());
                user.setPhone(demoUser.getPhone());
                user.setPassword(passwordEncoder.encode(
                        StringUtils.hasText(demoUser.getPassword()) ? demoUser.getPassword() : "123456"
                ));
                user.setNickname(StringUtils.hasText(demoUser.getNickname()) ? demoUser.getNickname() : "演示用户");
                user.setBindStatus(BIND_STATUS_UNBOUND);
                user.setRoleType(ROLE_TYPE_USER);
                user.setStatus(USER_STATUS_NORMAL);
                user.setDeleted(0);
                userMapper.insert(user);
                log.info("已初始化小程序演示账号: {}", demoUser.getPhone());
            } catch (Exception exception) {
                log.warn("跳过小程序演示账号初始化，数据库当前不可用: {}", exception.getMessage());
            }
        };
    }
}
