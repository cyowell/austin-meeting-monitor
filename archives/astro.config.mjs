// @ts-check
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

// https://astro.build/config
export default defineConfig({
  site: 'https://austincouncil.app',
  outDir: '../docs/archives',
  base: '/archives',
  integrations: [
    sitemap({
      customPages: ['https://austincouncil.app/']
    })
  ]
});
