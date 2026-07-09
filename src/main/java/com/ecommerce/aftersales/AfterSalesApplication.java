package com.ecommerce.aftersales;

import com.ecommerce.aftersales.config.AgentGatewayProperties;
import com.ecommerce.aftersales.config.MiniappClientProperties;
import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.scheduling.annotation.EnableAsync;

@MapperScan("com.ecommerce.aftersales.mapper")
@SpringBootApplication
@EnableAsync
@EnableConfigurationProperties({AgentGatewayProperties.class, MiniappClientProperties.class})
public class AfterSalesApplication {

    public static void main(String[] args) {
        SpringApplication.run(AfterSalesApplication.class, args);
    }
}
