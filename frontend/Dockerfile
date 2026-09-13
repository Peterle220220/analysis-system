FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Next bakes rewrites into the production artifact, so the Docker network name
# must be available while building rather than only when the container starts.
ARG ASYS_BACKEND_URL=http://dashboard:8020
ENV ASYS_BACKEND_URL=${ASYS_BACKEND_URL}
# Cac ham thuan (cuon ao, giao dien Sang/Toi) co test rieng, chay bang chinh
# Node trong image: khong them thu vien test nao. Test hong thi build dung o day.
RUN npm test
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
