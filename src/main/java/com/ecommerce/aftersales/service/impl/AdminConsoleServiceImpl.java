package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.common.BizException;
import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.AgentOperationsView;
import com.ecommerce.aftersales.dto.AdminConsoleDtos.*;
import com.ecommerce.aftersales.entity.ChatSession;
import com.ecommerce.aftersales.entity.SysUser;
import com.ecommerce.aftersales.mapper.ChatSessionMapper;
import com.ecommerce.aftersales.mapper.SysUserMapper;
import com.ecommerce.aftersales.service.AgentOperationsMonitoringService;
import com.ecommerce.aftersales.service.AdminConsoleService;
import com.ecommerce.aftersales.util.JwtTokenUtil;
import lombok.RequiredArgsConstructor;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class AdminConsoleServiceImpl implements AdminConsoleService {

    private static final String ADMIN_MERCHANT_CODE = "ADMIN_PLATFORM";
    private static final String DEFAULT_AGENT_PASSWORD = "123456";
    private static final int STATUS_ACTIVE = 1;
    private static final int STATUS_PENDING_APPROVAL = 2;
    private static final DateTimeFormatter DATE_TIME_FORMATTER = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final SysUserMapper sysUserMapper;
    private final ChatSessionMapper chatSessionMapper;
    private final PasswordEncoder passwordEncoder;
    private final JwtTokenUtil jwtTokenUtil;
    private final AgentOperationsMonitoringService agentOperationsMonitoringService;

    @Override
    @Transactional(rollbackFor = Exception.class)
    public AdminLoginResponse login(AdminLoginRequest request) {
        if (!StringUtils.hasText(request.getAccount()) || !StringUtils.hasText(request.getPassword())) {
            throw new BizException("请输入管理员账号和密码");
        }
        SysUser admin = findAdminByAccount(request.getAccount().trim());
        if (admin == null && "admin_demo".equals(request.getAccount().trim())) {
            admin = createDemoAdmin();
        }
        if (admin == null || !passwordEncoder.matches(request.getPassword(), admin.getPassword())) {
            throw new BizException("管理员账号或密码错误");
        }
        if (!Integer.valueOf(1).equals(admin.getStatus())) {
            throw new BizException(403, "管理员账号已被禁用");
        }
        admin.setLastLoginTime(LocalDateTime.now());
        admin.setOnlineStatus(1);
        sysUserMapper.updateById(admin);

        AdminLoginResponse response = new AdminLoginResponse();
        response.setToken(jwtTokenUtil.generateToken(admin.getId(), Optional.ofNullable(admin.getPhone()).orElse(admin.getUsername())));
        response.setAdmin(toAdminProfile(admin));
        return response;
    }

    @Override
    public void logout() {
    }

    @Override
    public AdminProfile getCurrentAdmin() {
        return toAdminProfile(ensureAdmin());
    }

    @Override
    public AdminOverview getOverview() {
        SysUser admin = ensureAdmin();
        List<SysUser> staffAccounts = listAgentUsers();
        long activeCount = staffAccounts.stream().filter(item -> Integer.valueOf(STATUS_ACTIVE).equals(item.getStatus())).count();
        long pendingCount = staffAccounts.stream().filter(item -> Integer.valueOf(STATUS_PENDING_APPROVAL).equals(item.getStatus())).count();
        long disabledCount = staffAccounts.size() - activeCount - pendingCount;
        long onlineCount = staffAccounts.stream().filter(item -> Integer.valueOf(1).equals(item.getOnlineStatus())).count();
        long merchantCount = staffAccounts.stream()
                .map(item -> Optional.ofNullable(item.getMerchantCode()).orElse(""))
                .filter(StringUtils::hasText)
                .distinct()
                .count();

        AdminOverview overview = new AdminOverview();
        overview.setGreeting("您好，" + Optional.ofNullable(admin.getRealName()).orElse("管理员"));
        overview.setSubtitle("统一管理客服账号、商家归属与基础接待配置");
        overview.setStats(List.of(
                stat("客服账号", staffAccounts.size(), "blue"),
                stat("启用账号", activeCount, "green"),
                stat("待审批账号", pendingCount, "orange"),
                stat("在线客服", onlineCount, "orange"),
                stat("商家数量", merchantCount, "slate"),
                stat("停用账号", disabledCount, "red")
        ));
        overview.setFocus(List.of(
                "客服端注册仅提交申请，管理员审核通过后账号才能直接用账号密码登录。",
                "商家编码由管理员端维护，客服登录不再要求额外输入商家编码。",
                "管理员端可统一管理客服账号与商家归属，默认重置密码为 123456。",
                "当前管理员端先承接身份治理，后续再扩展知识库治理模块。"
        ));
        return overview;
    }

    @Override
    public AgentOperationsView getAgentOperations(String range) {
        ensureAdmin();
        return agentOperationsMonitoringService.load(range);
    }

    @Override
    public PageResult<ServiceAccountView> listServiceAccounts(long page, long size) {
        ensureAdmin();
        List<ServiceAccountView> records = listAgentUsers().stream()
                .map(this::toServiceAccountView)
                .toList();
        return PageResult.of(records, page, size);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ServiceAccountView createServiceAccount(ServiceAccountUpsertRequest request) {
        ensureAdmin();
        validateServiceAccountRequest(request);
        if (findStaffByAccountAnyMerchant(request.getAccount().trim()) != null) {
            throw new BizException("该账号已存在");
        }
        SysUser staff = new SysUser();
        staff.setUsername(request.getAccount().trim());
        staff.setPassword(passwordEncoder.encode(DEFAULT_AGENT_PASSWORD));
        staff.setMerchantCode(normalizeMerchantCode(request.getMerchantCode()));
        staff.setRealName(request.getRealName().trim());
        staff.setPhone(blankToNull(request.getPhone()));
        staff.setRoleType(toRoleType(request.getRole()));
        staff.setStatus(toStatusValue(request.getStatus()));
        staff.setOnlineStatus(0);
        staff.setMaxSessions(normalizeMaxSessions(request.getMaxSessionCount()));
        staff.setDeleted(0);
        sysUserMapper.insert(staff);
        return toServiceAccountView(staff);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public ServiceAccountView updateServiceAccount(Long accountId, ServiceAccountUpsertRequest request) {
        ensureAdmin();
        SysUser staff = findAgentById(accountId);
        if (StringUtils.hasText(request.getAccount())) {
            SysUser duplicate = findStaffByAccountAnyMerchant(request.getAccount().trim());
            if (duplicate != null && !duplicate.getId().equals(staff.getId())) {
                throw new BizException("该账号已存在");
            }
            staff.setUsername(request.getAccount().trim());
        }
        if (StringUtils.hasText(request.getMerchantCode())) {
            staff.setMerchantCode(normalizeMerchantCode(request.getMerchantCode()));
        }
        if (StringUtils.hasText(request.getRealName())) {
            staff.setRealName(request.getRealName().trim());
        }
        if (request.getPhone() != null) {
            staff.setPhone(blankToNull(request.getPhone()));
        }
        if (StringUtils.hasText(request.getRole())) {
            staff.setRoleType(toRoleType(request.getRole()));
        }
        if (request.getStatus() != null) {
            staff.setStatus(toStatusValue(request.getStatus()));
        }
        if (request.getMaxSessionCount() != null) {
            staff.setMaxSessions(normalizeMaxSessions(request.getMaxSessionCount()));
        }
        validateServiceAccountEntity(staff);
        if (!Integer.valueOf(STATUS_ACTIVE).equals(staff.getStatus())) {
            staff.setOnlineStatus(0);
        }
        sysUserMapper.updateById(staff);
        return toServiceAccountView(staff);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public PasswordResetView resetServiceAccountPassword(Long accountId) {
        ensureAdmin();
        SysUser staff = findAgentById(accountId);
        staff.setPassword(passwordEncoder.encode(DEFAULT_AGENT_PASSWORD));
        sysUserMapper.updateById(staff);

        PasswordResetView view = new PasswordResetView();
        view.setAccountId(staff.getId());
        view.setAccount(staff.getUsername());
        view.setTemporaryPassword(DEFAULT_AGENT_PASSWORD);
        return view;
    }

    private void validateServiceAccountRequest(ServiceAccountUpsertRequest request) {
        if (!StringUtils.hasText(request.getAccount())
                || !StringUtils.hasText(request.getRealName())
                || !StringUtils.hasText(request.getMerchantCode())) {
            throw new BizException("请填写账号、姓名和商家编码");
        }
    }

    private void validateServiceAccountEntity(SysUser staff) {
        if (!StringUtils.hasText(staff.getUsername())
                || !StringUtils.hasText(staff.getRealName())
                || !StringUtils.hasText(staff.getMerchantCode())) {
            throw new BizException("请填写账号、姓名和商家编码");
        }
    }

    private List<SysUser> listAgentUsers() {
        return sysUserMapper.selectList(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getRoleType, "AGENT")
                .orderByDesc(SysUser::getCreateTime));
    }

    private SysUser findAdminByAccount(String account) {
        return sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, account)
                .eq(SysUser::getRoleType, "ADMIN")
                .last("limit 1"));
    }

    private SysUser findStaffByAccountAnyMerchant(String account) {
        return sysUserMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, account)
                .eq(SysUser::getRoleType, "AGENT")
                .last("limit 1"));
    }

    private SysUser findAgentById(Long accountId) {
        SysUser staff = sysUserMapper.selectById(accountId);
        if (staff == null || !"AGENT".equalsIgnoreCase(staff.getRoleType())) {
            throw new BizException(404, "客服账号不存在");
        }
        return staff;
    }

    private SysUser ensureAdmin() {
        Long adminId = currentUserId();
        if (adminId == null) {
            throw new BizException(401, "未登录，请先登录管理员账号");
        }
        SysUser admin = sysUserMapper.selectById(adminId);
        if (admin == null || !"ADMIN".equalsIgnoreCase(admin.getRoleType())) {
            throw new BizException(403, "当前账号没有管理员权限");
        }
        if (!Integer.valueOf(1).equals(admin.getStatus())) {
            throw new BizException(403, "管理员账号已被禁用");
        }
        return admin;
    }

    private SysUser createDemoAdmin() {
        SysUser admin = new SysUser();
        admin.setUsername("admin_demo");
        admin.setPassword(passwordEncoder.encode(DEFAULT_AGENT_PASSWORD));
        admin.setMerchantCode(ADMIN_MERCHANT_CODE);
        admin.setRealName("Platform Admin");
        admin.setPhone("13800138000");
        admin.setRoleType("ADMIN");
        admin.setStatus(1);
        admin.setOnlineStatus(1);
        admin.setMaxSessions(0);
        admin.setDeleted(0);
        sysUserMapper.insert(admin);
        return admin;
    }

    private AdminProfile toAdminProfile(SysUser admin) {
        AdminProfile profile = new AdminProfile();
        profile.setAdminId(admin.getId());
        profile.setAccount(admin.getUsername());
        profile.setRealName(admin.getRealName());
        profile.setRole("ADMIN");
        profile.setScope("账号治理与运营配置");
        profile.setPhone(admin.getPhone());
        return profile;
    }

    private ServiceAccountView toServiceAccountView(SysUser staff) {
        ServiceAccountView view = new ServiceAccountView();
        view.setId(staff.getId());
        view.setStaffNo("CS" + String.format("%04d", staff.getId()));
        view.setAccount(staff.getUsername());
        view.setRealName(staff.getRealName());
        view.setMerchantCode(normalizeMerchantCode(staff.getMerchantCode()));
        view.setPhone(staff.getPhone());
        view.setRole("CUSTOMER_SERVICE");
        view.setStatus(toStatusText(staff.getStatus()));
        view.setOnlineStatus(toOnlineStatusText(staff.getOnlineStatus()));
        view.setMaxSessionCount(staff.getMaxSessions());
        view.setCurrentSessionCount(currentSessionCount(staff.getId()));
        view.setKnowledgeScope(Optional.ofNullable(staff.getMerchantCode()).orElse("MERCHANT_DEMO"));
        view.setLastLoginTime(format(staff.getLastLoginTime()));
        view.setNote(Integer.valueOf(STATUS_PENDING_APPROVAL).equals(staff.getStatus())
                ? "该账号来自客服端注册申请，待管理员审核。"
                : "管理员维护客服账号与商家归属。");
        return view;
    }

    private int currentSessionCount(Long staffId) {
        Long count = chatSessionMapper.selectCount(new LambdaQueryWrapper<ChatSession>()
                .eq(ChatSession::getHumanAgentId, staffId)
                .ne(ChatSession::getStatus, "CLOSED"));
        return count == null ? 0 : count.intValue();
    }

    private StatItem stat(String label, Object value, String accent) {
        StatItem item = new StatItem();
        item.setLabel(label);
        item.setValue(value);
        item.setAccent(accent);
        return item;
    }

    private String toOnlineStatusText(Integer onlineStatus) {
        return switch (Optional.ofNullable(onlineStatus).orElse(0)) {
            case 1 -> "ONLINE";
            case 2 -> "BUSY";
            default -> "OFFLINE";
        };
    }

    private Integer toStatusValue(String status) {
        if ("PENDING_APPROVAL".equalsIgnoreCase(status)) {
            return STATUS_PENDING_APPROVAL;
        }
        return "DISABLED".equalsIgnoreCase(status) ? 0 : STATUS_ACTIVE;
    }

    private String toStatusText(Integer status) {
        return switch (Optional.ofNullable(status).orElse(0)) {
            case STATUS_ACTIVE -> "ACTIVE";
            case STATUS_PENDING_APPROVAL -> "PENDING_APPROVAL";
            default -> "DISABLED";
        };
    }

    private String toRoleType(String role) {
        return StringUtils.hasText(role) && !"CUSTOMER_SERVICE".equalsIgnoreCase(role) ? role.trim() : "AGENT";
    }

    private int normalizeMaxSessions(Integer maxSessionCount) {
        return maxSessionCount == null || maxSessionCount < 1 ? 8 : maxSessionCount;
    }

    private String normalizeMerchantCode(String merchantCode) {
        return StringUtils.hasText(merchantCode) ? merchantCode.trim() : "MERCHANT_DEMO";
    }

    private String blankToNull(String value) {
        return StringUtils.hasText(value) ? value.trim() : null;
    }

    private String format(LocalDateTime value) {
        return value == null ? "未登录" : DATE_TIME_FORMATTER.format(value);
    }

    private Long currentUserId() {
        ServletRequestAttributes attributes = (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        if (attributes == null) {
            return null;
        }
        String authorization = attributes.getRequest().getHeader("Authorization");
        if (!StringUtils.hasText(authorization) || !authorization.startsWith("Bearer ")) {
            return null;
        }
        return jwtTokenUtil.parseUserIdOrNull(authorization.substring("Bearer ".length()));
    }
}
