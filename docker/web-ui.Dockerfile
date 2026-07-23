FROM node:22-alpine AS build

ENV HUSKY=0

RUN corepack enable && corepack prepare pnpm@10.15.1 --activate

WORKDIR /build
COPY examples/web_ui/package.json \
     examples/web_ui/pnpm-lock.yaml \
     examples/web_ui/pnpm-workspace.yaml ./
COPY examples/web_ui/backend/package.json ./backend/package.json
COPY examples/web_ui/frontend/package.json ./frontend/package.json

RUN --mount=type=cache,id=pnpm,target=/pnpm/store \
    pnpm config set store-dir /pnpm/store \
    && pnpm install --frozen-lockfile

COPY examples/web_ui/frontend ./frontend
RUN pnpm --filter frontend build

FROM nginx:1.28-alpine

COPY docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /build/frontend/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q -O - http://127.0.0.1:8080/api/health | grep -q '"status":"ok"' || exit 1

CMD ["nginx", "-g", "daemon off;"]
