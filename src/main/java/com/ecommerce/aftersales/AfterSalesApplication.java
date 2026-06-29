package com.ecommerce.aftersales;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@MapperScan("com.ecommerce.aftersales.mapper")
@SpringBootApplication
public class AfterSalesApplication {

    public static void main(String[] args) {
        SpringApplication.run(AfterSalesApplication.class, args);
    }
}
