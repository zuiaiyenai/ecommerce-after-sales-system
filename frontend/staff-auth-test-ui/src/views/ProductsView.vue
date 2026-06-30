<script setup>
import { computed, inject, onMounted, reactive, ref } from 'vue';
import {
  getProducts,
  createProduct,
  updateProduct,
  updateProductStatus,
  uploadProductImage
} from '../api/merchantCs';

const shell = inject('merchantCsShell', null);

const loading = ref(false);
const products = ref([]);
const total = ref(0);
const page = ref(1);
const pageSize = ref(20);
const keyword = ref('');
const statusFilter = ref('');

const showModal = ref(false);
const editingProduct = ref(null);
const imageErrors = ref(new Set());
const imageInput = ref(null);
const form = reactive({
  productName: '',
  productCode: '',
  category: '',
  description: '',
  mainImage: '',
  images: [],
  price: '',
  status: 'ON_SALE'
});
const formSaving = ref(false);
const imageUploading = ref(false);
const formError = ref('');

const statusOptions = [
  { key: '', label: '全部' },
  { key: 'ON_SALE', label: '上架' },
  { key: 'OFF_SALE', label: '下架' }
];

const categoryOptions = ['服装', '数码', '日用', '鞋靴', '食品', '家居', '其他'];

function apiOrigin() {
  return (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080')
    .replace(/\/+$/, '')
    .replace(/\/api$/, '');
}

async function loadProducts() {
  loading.value = true;
  try {
    const result = await getProducts({
      page: page.value,
      size: pageSize.value,
      status: statusFilter.value || undefined,
      keyword: keyword.value || undefined
    });
    products.value = result.records || [];
    total.value = result.total || 0;
  } catch (e) {
    shell?.setAction(e.message || '加载商品失败');
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editingProduct.value = null;
  form.productName = '';
  form.productCode = '';
  form.category = '';
  form.description = '';
  form.mainImage = '';
  form.images = [];
  form.price = '';
  form.status = 'ON_SALE';
  imageUploading.value = false;
  formError.value = '';
  if (imageInput.value) {
    imageInput.value.value = '';
  }
  showModal.value = true;
}

function openEdit(product) {
  editingProduct.value = product;
  form.productName = product.productName || '';
  form.productCode = product.productCode || '';
  form.category = product.category || '';
  form.description = product.description || '';
  form.images = syncProductImages(product);
  form.mainImage = product.mainImage || form.images[0] || '';
  form.price = product.price != null ? String(product.price) : '';
  form.status = product.status || 'ON_SALE';
  imageUploading.value = false;
  formError.value = '';
  if (imageInput.value) {
    imageInput.value.value = '';
  }
  showModal.value = true;
}

async function handleSave() {
  if (imageUploading.value) {
    formError.value = '图片还在上传中，请稍后再保存';
    return;
  }
  if (!form.productName.trim()) {
    formError.value = '商品名称不能为空';
    return;
  }
  if (!form.price || Number(form.price) < 0) {
    formError.value = '请输入有效价格';
    return;
  }
  formSaving.value = true;
  formError.value = '';
  try {
    normalizeFormImages();
    const data = {
      productName: form.productName.trim(),
      productCode: form.productCode.trim() || undefined,
      category: form.category || undefined,
      description: form.description.trim() || undefined,
      mainImage: form.mainImage.trim() || undefined,
      images: form.images,
      price: Number(form.price),
      status: form.status
    };
    if (editingProduct.value) {
      await updateProduct(editingProduct.value.id, data);
      shell?.setAction('商品已更新');
    } else {
      await createProduct(data);
      shell?.setAction('商品已创建');
    }
    showModal.value = false;
    await loadProducts();
  } catch (e) {
    formError.value = e.message || '保存失败';
  } finally {
    formSaving.value = false;
  }
}

async function handleMainImageChange(event) {
  const file = event.target.files?.[0];
  if (!file) {
    return;
  }
  if (!file.type.startsWith('image/')) {
    formError.value = '只能上传图片文件';
    event.target.value = '';
    return;
  }
  if (file.size > 10 * 1024 * 1024) {
    formError.value = '图片大小不能超过 10MB';
    event.target.value = '';
    return;
  }
  imageUploading.value = true;
  formError.value = '';
  try {
    const result = await uploadProductImage(file);
    form.mainImage = result.url || '';
    form.images = form.mainImage ? [form.mainImage] : [];
    imageErrors.value = new Set();
    shell?.setAction('商品图片已上传');
  } catch (e) {
    formError.value = e.message || '图片上传失败';
  } finally {
    imageUploading.value = false;
    event.target.value = '';
  }
}

function clearMainImage() {
  form.mainImage = '';
  form.images = [];
  if (imageInput.value) {
    imageInput.value.value = '';
  }
}

async function handleToggleStatus(product) {
  try {
    const newStatus = product.status === 'ON_SALE' ? 'OFF_SALE' : 'ON_SALE';
    await updateProductStatus(product.id, newStatus);
    product.status = newStatus;
    shell?.setAction(`商品已${newStatus === 'ON_SALE' ? '上架' : '下架'}`);
  } catch (e) {
    shell?.setAction(e.message || '操作失败');
  }
}

function handleSearch() {
  page.value = 1;
  loadProducts();
}

function priceText(val) {
  if (val == null) return '-';
  return Number(val).toFixed(2);
}

function imageUrl(src) {
  if (!src) return '';
  const value = String(src).trim();
  if (!value) return '';
  if (/^(https?:)?\/\//.test(value) || value.startsWith('data:') || value.startsWith('blob:')) {
    return value;
  }
  const origin = apiOrigin();
  if (value.startsWith('/api/')) {
    return `${origin}${value}`;
  }
  if (value.startsWith('/uploads/') || value.startsWith('/static/')) {
    return `${origin}/api${value}`;
  }
  if (value.startsWith('uploads/') || value.startsWith('static/')) {
    return `${origin}/api/${value}`;
  }
  if (value.startsWith('/')) {
    return `${origin}${value}`;
  }
  return `${origin}/api/${value}`;
}

function imageValue(product) {
  if (!product) return '';
  if (product.mainImage) {
    return product.mainImage;
  }
  if (Array.isArray(product.images) && product.images.length) {
    return product.images[0];
  }
  if (typeof product.images === 'string' && product.images.trim()) {
    try {
      const parsed = JSON.parse(product.images);
      if (Array.isArray(parsed) && parsed.length) {
        return parsed[0];
      }
    } catch {
      return product.images;
    }
  }
  return '';
}

function hasProductImage(product) {
  return Boolean(imageValue(product));
}

function productImageUrl(product) {
  return imageUrl(imageValue(product));
}

function formImageUrl() {
  return imageUrl(form.mainImage);
}

function normalizeImageList(images) {
  if (Array.isArray(images)) {
    return images;
  }
  if (typeof images === 'string' && images.trim()) {
    try {
      const parsed = JSON.parse(images);
      return Array.isArray(parsed) ? parsed : [images];
    } catch {
      return [images];
    }
  }
  return [];
}

function syncProductImages(product) {
  if (!product) return [];
  return normalizeImageList(product.images);
}

function normalizeFormImages() {
  form.images = normalizeImageList(form.images);
  if (form.mainImage && !form.images.includes(form.mainImage)) {
    form.images = [form.mainImage, ...form.images];
  }
}

function productImageKey(product) {
  return `${product.id}:${imageValue(product) || ''}`;
}

function shouldShowProductImage(product) {
  return hasProductImage(product) && !imageErrors.value.has(productImageKey(product));
}

function markProductImageError(product) {
  const next = new Set(imageErrors.value);
  next.add(productImageKey(product));
  imageErrors.value = next;
}

onMounted(loadProducts);
</script>

<template>
  <section class="products-page">
    <div class="page-toolbar">
      <div class="toolbar-left">
        <input
          v-model.trim="keyword"
          class="search-input"
          placeholder="搜索商品名称/编码..."
          @keyup.enter="handleSearch"
        />
        <select v-model="statusFilter" class="filter-select" @change="handleSearch">
          <option v-for="opt in statusOptions" :key="opt.key" :value="opt.key">{{ opt.label }}</option>
        </select>
        <button type="button" class="ghost-mini" @click="handleSearch">搜索</button>
      </div>
      <button type="button" class="template-primary-blue" @click="openCreate">+ 新增商品</button>
    </div>

    <div v-if="loading" class="loading-state">加载中...</div>

    <div v-else class="products-table-wrap">
      <table class="products-table" v-if="products.length">
        <thead>
          <tr>
            <th>商品</th>
            <th>编码</th>
            <th>分类</th>
            <th>价格</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="p in products" :key="p.id">
            <td>
              <div class="product-name-cell">
                <img
                  v-if="shouldShowProductImage(p)"
                  class="product-thumb-sm"
                  :src="productImageUrl(p)"
                  :alt="p.productName"
                  @error="markProductImageError(p)"
                />
                <span v-else class="product-thumb-sm fallback">📦</span>
                <span>{{ p.productName }}</span>
              </div>
            </td>
            <td>{{ p.productCode || '-' }}</td>
            <td>{{ p.category || '-' }}</td>
            <td>¥{{ priceText(p.price) }}</td>
            <td>
              <span :class="['status-tag', p.status === 'ON_SALE' ? 'on-sale' : 'off-sale']">
                {{ p.status === 'ON_SALE' ? '上架' : '下架' }}
              </span>
            </td>
            <td>
              <div class="action-btns">
                <button type="button" class="ghost-mini" @click="openEdit(p)">编辑</button>
                <button type="button" class="ghost-mini" @click="handleToggleStatus(p)">
                  {{ p.status === 'ON_SALE' ? '下架' : '上架' }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty-state">暂无商品数据</div>
    </div>

    <!-- Create/Edit Modal -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal-box">
        <h3>{{ editingProduct ? '编辑商品' : '新增商品' }}</h3>

        <label class="form-field">
          <span>商品名称 <em>*</em></span>
          <input v-model.trim="form.productName" placeholder="请输入商品名称" />
        </label>

        <label class="form-field">
          <span>商品编码</span>
          <input v-model.trim="form.productCode" placeholder="请输入商品编码" />
        </label>

        <label class="form-field">
          <span>分类</span>
          <select v-model="form.category">
            <option value="">请选择分类</option>
            <option v-for="c in categoryOptions" :key="c" :value="c">{{ c }}</option>
          </select>
        </label>

        <label class="form-field">
          <span>价格 <em>*</em></span>
          <input v-model="form.price" type="number" step="0.01" min="0" placeholder="请输入价格" />
        </label>

        <label class="form-field">
          <span>描述</span>
          <textarea v-model="form.description" rows="3" placeholder="请输入商品描述"></textarea>
        </label>

        <div class="form-field">
          <span>商品主图</span>
          <div class="image-upload-row">
            <img
              v-if="form.mainImage"
              class="product-image-preview"
              :src="formImageUrl()"
              alt="商品主图预览"
            />
            <div v-else class="product-image-placeholder">暂无图片</div>
            <div class="image-upload-actions">
              <label class="ghost-mini file-button">
                {{ imageUploading ? '上传中...' : '选择图片' }}
                <input
                  ref="imageInput"
                  type="file"
                  accept="image/*"
                  :disabled="imageUploading || formSaving"
                  @change="handleMainImageChange"
                />
              </label>
              <button
                v-if="form.mainImage"
                type="button"
                class="ghost-mini"
                :disabled="imageUploading || formSaving"
                @click="clearMainImage"
              >
                移除图片
              </button>
              <small>支持 JPG、PNG、WebP，最大 10MB</small>
            </div>
          </div>
        </div>

        <label class="form-field">
          <span>状态</span>
          <select v-model="form.status">
            <option value="ON_SALE">上架</option>
            <option value="OFF_SALE">下架</option>
          </select>
        </label>

        <div v-if="formError" class="status-banner error">{{ formError }}</div>

        <div class="modal-actions">
          <button type="button" class="ghost-mini" @click="showModal = false" :disabled="formSaving">取消</button>
          <button type="button" class="template-primary-blue" @click="handleSave" :disabled="formSaving">
            {{ formSaving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.products-page {
  padding: 20px 28px;
}

.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
  flex-wrap: wrap;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.search-input {
  width: 220px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
}

.filter-select {
  height: 36px;
  padding: 0 10px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
  background: #fff;
}

.products-table-wrap {
  background: #fff;
  border-radius: 10px;
  border: 1px solid rgba(0,0,0,0.06);
  overflow: hidden;
}

.products-table {
  width: 100%;
  border-collapse: collapse;
}

.products-table th,
.products-table td {
  text-align: left;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
  font-size: 14px;
}

.products-table th {
  background: #fafafa;
  font-weight: 600;
  color: #555;
  font-size: 13px;
}

.product-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.product-thumb-sm {
  width: 32px;
  height: 32px;
  display: block;
  object-fit: cover;
  background: #f5f3ef;
  border-radius: 6px;
  border: 1px solid rgba(0,0,0,0.06);
  flex-shrink: 0;
}

.product-thumb-sm.fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
}

.status-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-tag.on-sale {
  background: #e6f7e6;
  color: #389e0d;
}

.status-tag.off-sale {
  background: #fff1f0;
  color: #cf1322;
}

.action-btns {
  display: flex;
  gap: 6px;
}

.empty-state,
.loading-state {
  padding: 40px;
  text-align: center;
  color: #999;
}

/* Modal */
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.3);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-box {
  background: #fff;
  border-radius: 12px;
  padding: 28px;
  width: 480px;
  max-height: 80vh;
  overflow-y: auto;
}

.modal-box h3 {
  margin: 0 0 20px;
  font-size: 18px;
}

.form-field {
  display: block;
  margin-bottom: 14px;
}

.form-field span {
  display: block;
  margin-bottom: 4px;
  font-size: 14px;
  font-weight: 500;
  color: #333;
}

.form-field span em {
  color: #f44;
  font-style: normal;
}

.form-field input,
.form-field select,
.form-field textarea {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 6px;
  font-size: 14px;
}

.image-upload-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.product-image-preview,
.product-image-placeholder {
  width: 88px;
  height: 88px;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
  background: #f8fafc;
  flex-shrink: 0;
}

.product-image-preview {
  display: block;
  object-fit: cover;
}

.product-image-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #94a3b8;
  font-size: 13px;
}

.image-upload-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.image-upload-actions small {
  width: 100%;
  color: #94a3b8;
  font-size: 12px;
}

.file-button {
  position: relative;
  overflow: hidden;
}

.file-button input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.status-banner.error {
  background: #fff1f0;
  color: #cf1322;
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 14px;
  font-size: 13px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  margin-top: 20px;
}

.template-primary-blue {
  padding: 8px 20px;
  background: #1677ff;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
}

.template-primary-blue:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ghost-mini {
  padding: 6px 14px;
  background: transparent;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  color: #333;
}

.ghost-mini:hover {
  border-color: #1677ff;
  color: #1677ff;
}
</style>
