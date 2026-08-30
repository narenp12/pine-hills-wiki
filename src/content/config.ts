import { defineCollection, z } from 'astro:content';
import { docsSchema } from '@astrojs/starlight/schema';

// Loose docs collection: require only title + description; allow optional
// season/year frontmatter emitted by scripts/generate.py. Keeps the build
// green even if a generated page omits properties.
export const collections = {
  docs: defineCollection({
    schema: docsSchema({
      extend: z.object({
        season: z.number().optional(),
        year: z.number().optional(),
      }),
    }),
  }),
};
