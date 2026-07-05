package com.ecommerce.aftersales.config;

import com.fasterxml.jackson.databind.cfg.CoercionAction;
import com.fasterxml.jackson.databind.cfg.CoercionInputShape;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;
import com.fasterxml.jackson.databind.type.LogicalType;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 解决 JS 大数精度丢失问题：
 * 1. Long 序列化为字符串（JS 只能安全表示 < 2^53 的整数，雪花ID 超出范围）
 * 2. 字符串自动反序列化为 Long/Integer（前端发回字符串ID）
 * Integer 和 BigDecimal 保持数字格式，前端算术不受影响
 */
@Configuration
public class JacksonConfig {

    @Bean
    public Jackson2ObjectMapperBuilderCustomizer jacksonCustomizer() {
        return builder -> {
            // 序列化：Long → String
            builder.serializerByType(Long.class, ToStringSerializer.instance);
            builder.serializerByType(long.class, ToStringSerializer.instance);
            // 反序列化：String → Long/Integer
            builder.postConfigurer(mapper -> {
                mapper.coercionConfigFor(LogicalType.Integer)
                        .setCoercion(CoercionInputShape.String, CoercionAction.TryConvert);
            });
        };
    }
}
