FROM node:20-alpine AS builder

RUN apk add --no-cache openssl

WORKDIR /app

COPY package.json package-lock.json turbo.json ./
COPY apps/node-api/package.json apps/node-api/
COPY packages/risk-engine/package.json packages/risk-engine/
COPY packages/incident-fingerprint/package.json packages/incident-fingerprint/
COPY packages/incident-formation/package.json packages/incident-formation/
COPY packages/adaptive-sampling/package.json packages/adaptive-sampling/
COPY packages/db/package.json packages/db/

RUN npm install --ignore-scripts

COPY . .

RUN --mount=type=cache,target=/app/node_modules/.cache/turbo npx turbo build
RUN npm run db:generate

FROM node:20-alpine AS runtime

RUN apk add --no-cache python3 py3-pip py3-setuptools openssl build-base python3-dev

WORKDIR /app

COPY packages/evaluator/requirements.txt /tmp/evaluator-requirements.txt
COPY packages/issue-agent/requirements.txt /tmp/issue-agent-requirements.txt

RUN pip install --no-cache-dir --break-system-packages --target=/usr/lib/python3.12/site-packages -r /tmp/evaluator-requirements.txt -r /tmp/issue-agent-requirements.txt

COPY --from=builder /app/node_modules ./node_modules

COPY --from=builder /app/packages/db/dist ./packages/db/dist
COPY --from=builder /app/packages/db/prisma ./packages/db/prisma
COPY --from=builder /app/packages/db/package.json ./packages/db/

COPY --from=builder /app/packages/risk-engine/dist ./packages/risk-engine/dist
COPY --from=builder /app/packages/risk-engine/package.json ./packages/risk-engine/

COPY --from=builder /app/packages/incident-fingerprint/dist ./packages/incident-fingerprint/dist
COPY --from=builder /app/packages/incident-fingerprint/package.json ./packages/incident-fingerprint/

COPY --from=builder /app/packages/incident-formation/dist ./packages/incident-formation/dist
COPY --from=builder /app/packages/incident-formation/package.json ./packages/incident-formation/

COPY --from=builder /app/packages/adaptive-sampling/dist ./packages/adaptive-sampling/dist
COPY --from=builder /app/packages/adaptive-sampling/package.json ./packages/adaptive-sampling/

COPY --from=builder /app/apps/node-api/dist ./apps/node-api/dist
COPY --from=builder /app/apps/node-api/package.json ./apps/node-api/
COPY --from=builder /app/node_modules/.prisma ./node_modules/.prisma

COPY packages/evaluator/src ./packages/evaluator/src
COPY packages/issue-agent/src ./packages/issue-agent/src

RUN rm -rf node_modules/@void-server && \
    mkdir -p node_modules/@void-server && \
    ln -s ../../packages/db node_modules/@void-server/db && \
    ln -s ../../packages/risk-engine node_modules/@void-server/risk-engine && \
    ln -s ../../packages/incident-fingerprint node_modules/@void-server/incident-fingerprint && \
    ln -s ../../packages/incident-formation node_modules/@void-server/incident-formation && \
    ln -s ../../packages/adaptive-sampling node_modules/@void-server/adaptive-sampling

COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

RUN addgroup -S void && adduser -S void -G void
USER void

EXPOSE 3001

ENTRYPOINT ["/app/docker-entrypoint.sh"]
