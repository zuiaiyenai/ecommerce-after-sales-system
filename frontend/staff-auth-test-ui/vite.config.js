import { fileURLToPath, URL } from 'node:url';
import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const useMockAdapter = mode === 'mock';
  if (command === 'build' && !useMockAdapter && !env.VITE_API_BASE_URL) {
    throw new Error('生产构建必须配置 VITE_API_BASE_URL，禁止回退到 mock adapter');
  }
  return {
    plugins: [vue()],
    resolve: {
      alias: {
        '@merchantCs': fileURLToPath(new URL(
          useMockAdapter ? './src/api/merchantCs.mock.js' : './src/api/merchantCs.real.js',
          import.meta.url
        ))
      }
    }
  };
});
