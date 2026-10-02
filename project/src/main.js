// Vue 应用入口：加载全局样式并把根组件挂载到 index.html 的 #app 节点。
import { createApp } from 'vue'
import App from './App.vue'
import './styles.css'

createApp(App).mount('#app')
