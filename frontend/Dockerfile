FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# API URL is baked at build time for the static client bundle.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build

FROM node:22-slim
RUN useradd --create-home --uid 10001 splitshield
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build --chown=splitshield /app/.next ./.next
COPY --from=build --chown=splitshield /app/node_modules ./node_modules
COPY --from=build --chown=splitshield /app/package.json ./package.json
COPY --from=build --chown=splitshield /app/public ./public
USER splitshield
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD node -e "fetch('http://localhost:3000/').then(r=>{if(!r.ok)process.exit(1)}).catch(()=>process.exit(1))"
CMD ["npx", "next", "start", "--port", "3000"]
