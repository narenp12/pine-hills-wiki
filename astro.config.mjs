// astro.config.mjs
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sitemap from '@astrojs/sitemap';
import { readFileSync } from 'node:fs';
import { remarkWikilinkCustom } from './src/remark-wikilink-custom.mjs';

// Title -> slug permalink map (run `node scripts/wikilink-map.mjs` first / via prebuild).
// Referenced by the custom wikilink resolver, which also reads it directly.
const permalinks = JSON.parse(readFileSync('permalinks.json', 'utf8'));
const BASE = '/pine-hills-wiki';

export default defineConfig({
  base: BASE,
  site: 'https://narenp12.github.io',
  integrations: [
    starlight({
      title: 'Pine Hills Fantasy Football League',
      description: 'The collaborative history of the Pine Hills Fantasy Football League, established 2016.',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/narenp12/pine-hills-wiki' }],
      customCss: ['./src/styles/wikipedia.css'],
      components: {
        Header: './src/components/Header.astro',
        Footer: './src/components/Footer.astro',
      },
      sidebar: [
        { label: 'Home', link: '/' },
        { label: 'Seasons', items: [{ autogenerate: { directory: 'seasons' } }] },
        { label: 'Teams', items: [{ autogenerate: { directory: 'teams' } }] },
        { label: 'Records', link: '/records/' },
        { label: 'Champions', link: '/champions/' },
        { label: 'Playoffs', link: '/playoffs/' },
        { label: 'Draft History', items: [{ autogenerate: { directory: 'draft' } }] },
        { label: 'Lore', link: '/lore/' },
      ],
    }),
    sitemap(),
  ],
  markdown: {
    remarkPlugins: [remarkWikilinkCustom],
  },
});
