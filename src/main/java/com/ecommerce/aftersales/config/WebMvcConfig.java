package com.ecommerce.aftersales.config;

import com.ecommerce.aftersales.common.resolver.CurrentStaffIdArgumentResolver;
import com.ecommerce.aftersales.common.resolver.CurrentUserIdArgumentResolver;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.converter.json.MappingJackson2HttpMessageConverter;
import org.springframework.http.converter.StringHttpMessageConverter;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

@Configuration
public class WebMvcConfig implements WebMvcConfigurer {

    @Override
    public void addArgumentResolvers(List<HandlerMethodArgumentResolver> resolvers) {
        resolvers.add(new CurrentUserIdArgumentResolver());
        resolvers.add(new CurrentStaffIdArgumentResolver());
    }

    @Override
    public void extendMessageConverters(List<HttpMessageConverter<?>> converters) {
        for (HttpMessageConverter<?> converter : converters) {
            if (converter instanceof StringHttpMessageConverter stringConverter) {
                stringConverter.setDefaultCharset(StandardCharsets.UTF_8);
                List<MediaType> supportedMediaTypes = new ArrayList<>(stringConverter.getSupportedMediaTypes());
                supportedMediaTypes.add(new MediaType("text", "plain", StandardCharsets.UTF_8));
                supportedMediaTypes.add(new MediaType("text", "html", StandardCharsets.UTF_8));
                supportedMediaTypes.add(new MediaType("application", "json", StandardCharsets.UTF_8));
                stringConverter.setSupportedMediaTypes(supportedMediaTypes);
                continue;
            }
            if (converter instanceof MappingJackson2HttpMessageConverter jacksonConverter) {
                jacksonConverter.setDefaultCharset(StandardCharsets.UTF_8);
                List<MediaType> supportedMediaTypes = new ArrayList<>(jacksonConverter.getSupportedMediaTypes());
                supportedMediaTypes.add(new MediaType("application", "json", StandardCharsets.UTF_8));
                supportedMediaTypes.add(new MediaType("application", "*+json", StandardCharsets.UTF_8));
                jacksonConverter.setSupportedMediaTypes(supportedMediaTypes);
            }
        }
    }
}
