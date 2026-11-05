FROM node:22-bookworm-slim AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
RUN npm ci
COPY apps/web ./apps/web
RUN npm run build

FROM node:22-bookworm-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
RUN groupadd --gid 10001 fastlane && useradd --uid 10001 --gid 10001 --create-home fastlane
COPY --from=build --chown=fastlane:fastlane /app/apps/web/.next/standalone ./
COPY --from=build --chown=fastlane:fastlane /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=build --chown=fastlane:fastlane /app/apps/web/public ./apps/web/public
USER fastlane
EXPOSE 3000
CMD ["node", "apps/web/server.js"]
