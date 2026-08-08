package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.dto.EmotionPolicyDtos.*;

import java.util.List;

public interface EmotionPolicyService {

    EmotionPolicyWorkspace getWorkspace();

    List<EmotionPolicyVersionItem> listVersions();

    EmotionPolicyWorkspace saveDraft(EmotionPolicySaveRequest request);

    EmotionPolicyWorkspace publish(EmotionPolicyPublishRequest request);

    EmotionPolicyWorkspace rollback(EmotionPolicyRollbackRequest request);

    EmotionPolicyTestResponse testPolicy(EmotionPolicyTestRequest request);
}
