import { createRouter, createWebHistory } from 'vue-router';
import AppLayout from '../components/AppLayout.vue';
import AdminLayout from '../components/AdminLayout.vue';
import DashboardView from '../views/DashboardView.vue';
import LoginView from '../views/LoginView.vue';
import AdminLoginView from '../views/AdminLoginView.vue';
import AdminDashboardView from '../views/AdminDashboardView.vue';
import AdminAccountsView from '../views/AdminAccountsView.vue';
import AdminKnowledgeView from '../views/AdminKnowledgeView.vue';
import SessionsView from '../views/SessionsView.vue';
import SessionDetailView from '../views/SessionDetailView.vue';
import TicketsView from '../views/TicketsView.vue';
import TicketDetailView from '../views/TicketDetailView.vue';
import OrdersView from '../views/OrdersView.vue';
import OrderDetailView from '../views/OrderDetailView.vue';
import NoticesView from '../views/NoticesView.vue';
import ProfileView from '../views/ProfileView.vue';
import ProductsView from '../views/ProductsView.vue';
import ReviewsView from '../views/ReviewsView.vue';

const TOKEN_KEY = 'merchant_cs_token';
const ADMIN_TOKEN_KEY = 'admin_console_token';

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', name: 'login', component: LoginView },
  { path: '/admin/login', name: 'adminLogin', component: AdminLoginView },
  {
    path: '/admin',
    component: AdminLayout,
    children: [
      { path: '', redirect: '/admin/dashboard' },
      { path: 'dashboard', name: 'adminDashboard', component: AdminDashboardView, meta: { title: '管理员首页' } },
      { path: 'accounts', name: 'adminAccounts', component: AdminAccountsView, meta: { title: '客服账号管理' } },
      { path: 'knowledge', name: 'adminKnowledge', component: AdminKnowledgeView, meta: { title: '知识治理' } }
    ]
  },
  {
    path: '/',
    component: AppLayout,
    children: [
      { path: 'dashboard', name: 'dashboard', component: DashboardView, meta: { title: '工作台首页' } },
      { path: 'sessions', name: 'sessions', component: SessionsView, meta: { title: '在线会话' } },
      { path: 'sessions/:sessionId', name: 'sessionDetail', component: SessionDetailView, meta: { title: '会话详情' } },
      { path: 'tickets', name: 'tickets', component: TicketsView, meta: { title: '售后申请' } },
      { path: 'tickets/:ticketId', name: 'ticketDetail', component: TicketDetailView, meta: { title: '申请详情' } },
      { path: 'orders', name: 'orders', component: OrdersView, meta: { title: '订单核验' } },
      { path: 'orders/:orderId', name: 'orderDetail', component: OrderDetailView, meta: { title: '订单详情' } },
      { path: 'products', name: 'products', component: ProductsView, meta: { title: '商品管理' } },
      { path: 'reviews', name: 'reviews', component: ReviewsView, meta: { title: '用户评价' } },
      { path: 'notices', name: 'notices', component: NoticesView, meta: { title: '消息通知' } },
      { path: 'profile', name: 'profile', component: ProfileView, meta: { title: '个人中心' } }
    ]
  }
];

const router = createRouter({
  history: createWebHistory(),
  routes
});

// Navigation guard: require auth for all routes except login
router.beforeEach((to, from, next) => {
  if (to.name === 'login' || to.name === 'adminLogin') {
    next();
    return;
  }

  if (to.path.startsWith('/admin')) {
    const adminToken = localStorage.getItem(ADMIN_TOKEN_KEY);
    if (!adminToken) {
      next('/admin/login');
      return;
    }
    next();
    return;
  }

  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) {
    next('/login');
    return;
  }
  next();
});

export default router;
