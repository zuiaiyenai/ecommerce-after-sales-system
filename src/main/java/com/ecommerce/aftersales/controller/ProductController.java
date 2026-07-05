package com.ecommerce.aftersales.controller;

import com.ecommerce.aftersales.common.ApiResponse;
import com.ecommerce.aftersales.service.ProductService;
import com.ecommerce.aftersales.vo.ProductVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequiredArgsConstructor
@RequestMapping("/products")
public class ProductController {

    private final ProductService productService;

    @GetMapping
    public ApiResponse<List<ProductVO>> listAll() {
        return ApiResponse.success("获取成功", productService.listAll());
    }

    @GetMapping("/{id}")
    public ApiResponse<ProductVO> getById(@PathVariable Long id) {
        ProductVO product = productService.getById(id);
        if (product == null) {
            return ApiResponse.fail(404, "商品不存在");
        }
        return ApiResponse.success("获取成功", product);
    }
}
