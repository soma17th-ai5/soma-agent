FROM oven/bun:1-alpine

WORKDIR /app

# 의존성 매니페스트 먼저 (캐시 활용)
COPY package.json bun.lock* bun.lockb* ./

RUN bun install --frozen-lockfile --production

COPY src ./src
COPY tsconfig.json ./

EXPOSE 3000

CMD ["bun", "run", "src/server.ts"]
