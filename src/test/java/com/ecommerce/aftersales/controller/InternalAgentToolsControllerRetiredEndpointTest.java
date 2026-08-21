package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.dto.InternalAgentToolDtos;
import org.junit.jupiter.api.Test;
import org.springframework.web.bind.annotation.PostMapping;

import java.util.Arrays;

import static org.assertj.core.api.Assertions.assertThat;

class InternalAgentToolsControllerRetiredEndpointTest {

    @Test
    void agentTicketCreationEndpointAndRequestDtoAreRemoved() {
        assertThat(Arrays.stream(InternalAgentToolsController.class.getDeclaredMethods())
                .map(method -> method.getAnnotation(PostMapping.class))
                .filter(annotation -> annotation != null)
                .flatMap(annotation -> Arrays.stream(annotation.value())))
                .doesNotContain("/aftersales/create");

        assertThat(Arrays.stream(InternalAgentToolDtos.class.getDeclaredClasses())
                .map(Class::getSimpleName))
                .doesNotContain("CreateTicketRequest");
    }
}
