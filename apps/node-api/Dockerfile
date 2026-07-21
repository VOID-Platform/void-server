FROM node:20-alpine

WORKDIR /app

# Copy root monorepo manifest files
COPY package.json package-lock.json turbo.json ./

# Copy packages and apps
COPY packages ./packages
COPY apps/node-api ./apps/node-api

# Install dependencies and generate Prisma client
RUN npm install
RUN npm run db:generate

# Expose Node.js API port
EXPOSE 3001

ENV NODE_ENV=production
ENV NODE_API_PORT=3001

CMD ["npm", "run", "dev", "--workspace=@void-server/node-api"]
