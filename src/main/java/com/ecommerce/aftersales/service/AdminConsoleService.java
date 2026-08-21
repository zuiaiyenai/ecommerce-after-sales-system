package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.common.PageResult;
import com.ecommerce.aftersales.dto.AdminAgentOperationsDtos.AgentOperationsView;
import com.ecommerce.aftersales.dto.AdminConsoleDtos.*;

public interface AdminConsoleService {

    AdminLoginResponse login(AdminLoginRequest request);

    void logout();

    AdminProfile getCurrentAdmin();

    AdminOverview getOverview();

    AgentOperationsView getAgentOperations(String range);

    PageResult<ServiceAccountView> listServiceAccounts(long page, long size);

    ServiceAccountView createServiceAccount(ServiceAccountUpsertRequest request);

    ServiceAccountView updateServiceAccount(Long accountId, ServiceAccountUpsertRequest request);

    PasswordResetView resetServiceAccountPassword(Long accountId);
}
