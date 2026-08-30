// astro.config.mjs
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  base: '/pine-hills-wiki',
  site: 'https://narenp12.github.io',
  integrations: [
    starlight({
      title: 'Pine Hills Fantasy Football League',
      description: 'The collaborative history of the Pine Hills Fantasy Football League, established 2016.',
      social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/narenp12/pine-hills-wiki' }],
      sidebar: [
        { label: 'Home', link: '/' },
        { label: 'Seasons', items: [{ autogenerate: { directory: 'seasons' } }] },
        { label: 'Teams', items: [{ autogenerate: { directory: 'teams' } }] },
        { label: 'Records', link: '/records/' },
        { label: 'Draft History', items: [{ autogenerate: { directory: 'draft' } }] },
        { label: 'Lore', link: '/lore/' },
      ],
    }),
    sitemap(),
  ],
});
