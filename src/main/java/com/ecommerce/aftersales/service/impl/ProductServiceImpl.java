package com.ecommerce.aftersales.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.ecommerce.aftersales.entity.ProductInfo;
import com.ecommerce.aftersales.mapper.ProductInfoMapper;
import com.ecommerce.aftersales.service.ProductService;
import com.ecommerce.aftersales.vo.ProductVO;
import lombok.RequiredArgsConstructor;
import org.springframework.beans.BeanUtils;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
public class ProductServiceImpl implements ProductService {

    private final ProductInfoMapper productInfoMapper;

    @Override
    public List<ProductVO> listAll() {
        LambdaQueryWrapper<ProductInfo> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(ProductInfo::getStatus, 1)
               .orderByAsc(ProductInfo::getId);
        return productInfoMapper.selectList(wrapper)
                .stream()
                .map(this::convertToVO)
                .collect(Collectors.toList());
    }

    @Override
    public ProductVO getById(Long id) {
        ProductInfo productInfo = productInfoMapper.selectById(id);
        if (productInfo == null) {
            return null;
        }
        return convertToVO(productInfo);
    }

    private ProductVO convertToVO(ProductInfo productInfo) {
        ProductVO vo = new ProductVO();
        BeanUtils.copyProperties(productInfo, vo);
        return vo;
    }
}
