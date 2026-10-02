FROM node:22-slim AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
