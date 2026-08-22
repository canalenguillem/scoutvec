# Frontend: build de Vite y nginx sirviendo el estatico. nginx tambien hace
# de proxy hacia el backend, que es lo que permite publicar un unico puerto.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig*.json vite.config.ts index.html ./
COPY src/ ./src/
COPY public/ ./public/
RUN npx tsc --noEmit && npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
