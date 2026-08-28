// @ts-check
import { defineConfig } from 'astro/config';

// https://astro.build/config
export default defineConfig({
  // 部署到 GitHub Pages 子路径时必须设置 site + base，
  // 否则构建产物的 CSS/JS/图片会引用绝对路径（/assets/...），
  // 在 https://<user>.github.io/<repo>/ 下会全部 404，导致页面无样式、不渲染。
  site: 'https://lin-zecheng.github.io',
  base: '/Atour_Collection/',
});
