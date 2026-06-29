package com.ecommerce.aftersales.service;

import com.ecommerce.aftersales.vo.ProductVO;

import java.util.List;

public interface ProductService {
    List<ProductVO> listAll();
    ProductVO getById(Long id);
}
