# Node.js + Fastify — multi-arch without QEMU: fastify is pure JS, so npm install runs once on
# the build host and the final stage only COPYs.
ARG NODE_VERSION=26.13.0
FROM --platform=$BUILDPLATFORM public.ecr.aws/docker/library/node:${NODE_VERSION}-slim AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

FROM public.ecr.aws/docker/library/node:${NODE_VERSION}-slim
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY package.json server.js ./
ENV NODE_ENV=production
EXPOSE 8080
CMD ["node", "server.js"]
