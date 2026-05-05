FROM oven/bun:1

WORKDIR /app

# 의존성 매니페스트 먼저 (캐시 활용)
COPY package.json bun.lock* bun.lockb* ./

# better-sqlite3 (opensoma의 CLI용 transitive)는 native build 필요.
# 우리는 SDK API만 쓰므로 install 시 build script 무시. 런타임에 toz 모듈을 import하지 않음.
RUN bun install --frozen-lockfile --production --ignore-scripts

COPY src ./src
COPY tsconfig.json ./

EXPOSE 3000

CMD ["bun", "run", "src/server.ts"]
