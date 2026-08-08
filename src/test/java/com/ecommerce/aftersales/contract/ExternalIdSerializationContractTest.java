package com.ecommerce.aftersales.contract;

import com.ecommerce.aftersales.dto.AdminConsoleDtos;
import com.ecommerce.aftersales.dto.AgentGatewayDtos;
import com.ecommerce.aftersales.dto.EmotionPolicyDtos;
import com.ecommerce.aftersales.dto.KnowledgeUploadDto;
import com.ecommerce.aftersales.dto.MerchantCsDtos;
import com.ecommerce.aftersales.dto.WsChatMessage;
import com.ecommerce.aftersales.response.AfterSalesLogResponse;
import com.ecommerce.aftersales.response.AfterSalesResponse;
import com.ecommerce.aftersales.service.impl.KnowledgeRetrievalServiceImpl;
import com.ecommerce.aftersales.vo.LoginResponse;
import com.ecommerce.aftersales.vo.OrderItemVO;
import com.ecommerce.aftersales.vo.OrderVO;
import com.ecommerce.aftersales.vo.ProductVO;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.test.util.ReflectionTestUtils;

import java.lang.reflect.Field;
import java.lang.reflect.Constructor;
import java.time.LocalDateTime;
import java.time.OffsetDateTime;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ExternalIdSerializationContractTest {

    private static final long LARGE_ID = 9_007_199_254_740_993L;

    @Test
    void everyLongIdentifierInExternalResponseTypesSerializesAsAJsonString() throws Exception {
        List<Class<?>> responseTypes = List.of(
                AdminConsoleDtos.AdminProfile.class,
                AdminConsoleDtos.ServiceAccountView.class,
                AdminConsoleDtos.PasswordResetView.class,
                AgentGatewayDtos.ChatRequest.class,
                AgentGatewayDtos.EmotionAnalyzeRequest.class,
                AgentGatewayDtos.PersistenceDto.class,
                EmotionPolicyDtos.EmotionPolicyDetail.class,
                KnowledgeUploadDto.KnowledgeInfo.class,
                MerchantCsDtos.StaffProfile.class,
                MerchantCsDtos.TodoItem.class,
                MerchantCsDtos.SessionView.class,
                MerchantCsDtos.MessageView.class,
                MerchantCsDtos.SessionAiAssistView.class,
                MerchantCsDtos.TicketView.class,
                MerchantCsDtos.TicketLogView.class,
                MerchantCsDtos.OrderView.class,
                MerchantCsDtos.OrderDetail.class,
                MerchantCsDtos.OrderProductItem.class,
                MerchantCsDtos.NoticeView.class,
                MerchantCsDtos.ProductView.class,
                MerchantCsDtos.ReviewView.class,
                WsChatMessage.class,
                AfterSalesLogResponse.class,
                AfterSalesResponse.class,
                LoginResponse.class,
                OrderItemVO.class,
                OrderVO.class,
                ProductVO.class
        );
        ObjectMapper mapper = new ObjectMapper();

        for (Class<?> responseType : responseTypes) {
            Object value = instantiate(responseType);
            for (Field field : responseType.getDeclaredFields()) {
                if (field.getType() != Long.class || !isIdentifier(field.getName())) {
                    continue;
                }
                field.setAccessible(true);
                field.set(value, LARGE_ID);
            }
            JsonNode json = mapper.valueToTree(value);
            for (Field field : responseType.getDeclaredFields()) {
                if (field.getType() == Long.class && isIdentifier(field.getName())) {
                    assertThat(json.path(field.getName()).isTextual())
                            .as("%s.%s", responseType.getSimpleName(), field.getName())
                            .isTrue();
                    assertThat(json.path(field.getName()).asText()).isEqualTo(String.valueOf(LARGE_ID));
                }
            }
        }
    }

    @Test
    void javaKnowledgeBoundaryMapsPublicCamelCaseToPythonSnakeCase() {
        AgentGatewayDtos.KnowledgeRetrieveRequest request = new AgentGatewayDtos.KnowledgeRetrieveRequest();
        request.setQuery("refund policy");
        request.setMerchantCode("MERCHANT_DEMO");
        request.setProductCategory("digital");
        request.setTopK(5);
        KnowledgeRetrievalServiceImpl service = new KnowledgeRetrievalServiceImpl(null, null);

        @SuppressWarnings("unchecked")
        Map<String, Object> payload = ReflectionTestUtils.invokeMethod(service, "toAgentPayload", request);

        assertThat(payload).containsEntry("merchant_code", "MERCHANT_DEMO");
        assertThat(payload).containsEntry("product_category", "digital");
        assertThat(payload).containsEntry("top_k", 5);
        assertThat(payload).doesNotContainKeys("merchantCode", "productCategory", "topK");
    }

    @Test
    void everyLocalDateTimeInExternalResponseTypesSerializesWithAnOffset() throws Exception {
        List<Class<?>> responseTypes = List.of(
                KnowledgeUploadDto.KnowledgeInfo.class,
                AfterSalesLogResponse.class,
                AfterSalesResponse.class,
                OrderVO.class
        );
        LocalDateTime value = LocalDateTime.of(2026, 7, 14, 12, 30, 45);
        ObjectMapper mapper = new ObjectMapper();

        for (Class<?> responseType : responseTypes) {
            Object response = instantiate(responseType);
            for (Field field : responseType.getDeclaredFields()) {
                if (field.getType() == LocalDateTime.class) {
                    field.setAccessible(true);
                    field.set(response, value);
                }
            }
            JsonNode json = mapper.valueToTree(response);
            for (Field field : responseType.getDeclaredFields()) {
                if (field.getType() == LocalDateTime.class) {
                    assertThat(OffsetDateTime.parse(json.path(field.getName()).asText())).isNotNull();
                }
            }
        }
    }

    private boolean isIdentifier(String fieldName) {
        String normalized = fieldName.replace("_", "").toLowerCase();
        return normalized.equals("id") || normalized.endsWith("id");
    }

    private Object instantiate(Class<?> responseType) throws ReflectiveOperationException {
        Constructor<?> constructor = List.of(responseType.getDeclaredConstructors()).stream()
                .min(Comparator.comparingInt(Constructor::getParameterCount))
                .orElseThrow();
        constructor.setAccessible(true);
        return constructor.newInstance(new Object[constructor.getParameterCount()]);
    }
}
