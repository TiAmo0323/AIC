// Vite 构建配置：启用 Vue 单文件组件编译插件。
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()]
})
