# Build context MUST be the monorepo root (not web/), since this is an npm workspace
# and web depends on the @redactproof/shared workspace package:
#   docker build -f web/Dockerfile -t redactproof-web .
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY web/package.json web/package.json
COPY shared/package.json shared/package.json
RUN npm ci

FROM node:22-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build --workspace web

# next.config.ts sets output: "standalone". Because the workspace root is the monorepo
# root, the standalone bundle nests as .next/standalone/web/server.js rather than at the
# top level - see next.config.ts comment / Next.js monorepo standalone-output docs.
FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

COPY --from=builder /app/web/.next/standalone ./
COPY --from=builder /app/web/.next/static ./web/.next/static
COPY --from=builder /app/web/public ./web/public

EXPOSE 3000
CMD ["node", "web/server.js"]
