package com.ecommerce.aftersales.config;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.entity.SysUser;
import com.ecommerce.aftersales.mapper.SysUserMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.CommandLineRunner;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.password.PasswordEncoder;

/**
 * 首次启动时自动创建默认客服账号，无需手动 INSERT SQL。
 */
@Configuration
@Slf4j
public class DataInitializer implements CommandLineRunner {

    private final SysUserMapper sysUserMapper;
    private final PasswordEncoder passwordEncoder;

    public DataInitializer(SysUserMapper sysUserMapper, PasswordEncoder passwordEncoder) {
        this.sysUserMapper = sysUserMapper;
        this.passwordEncoder = passwordEncoder;
    }

    @Override
    public void run(String... args) {
        try {
            String staffAccount = "cs_demo";
            String merchantCode = "MERCHANT_DEMO";

            SysUser existing = sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                    .eq(SysUser::getUsername, staffAccount)
                    .eq(SysUser::getMerchantCode, merchantCode)
                    .last("limit 1"));

            if (existing != null) {
                if (!passwordEncoder.matches("123456", existing.getPassword())) {
                    existing.setPassword(passwordEncoder.encode("123456"));
                    sysUserMapper.updateById(existing);
                    log.info("已重置默认客服账号 cs_demo 的密码为 123456");
                }
                return;
            }

            SysUser staff = new SysUser();
            staff.setUsername(staffAccount);
            staff.setPassword(passwordEncoder.encode("123456"));
            staff.setMerchantCode(merchantCode);
            staff.setRealName("林真");
            staff.setPhone("13800000001");
            staff.setEmail("cs_demo@example.com");
            staff.setRoleType("AGENT");
            staff.setStatus(1);
            staff.setOnlineStatus(1);
            staff.setMaxSessions(8);
            staff.setDeleted(0);
            sysUserMapper.insert(staff);

            log.info("已创建默认客服账号: cs_demo / 123456 / MERCHANT_DEMO");
        } catch (Exception exception) {
            log.warn("跳过默认客服账号初始化，数据库当前不可用: {}", exception.getMessage());
        }
    }
}
