# 多阶段构建：先构建前端静态资源，再由 Nginx 提供（设计文档第 10 章）
FROM node:22-alpine AS build
WORKDIR /app
# 先只拷依赖清单，装完再拷源码——利用 Docker 层缓存，
# 改业务代码不必重装依赖。必须连 package-lock.json 一起拷并用 npm ci：
# npm install 会按语义化范围重新解析版本，导致同一份代码两次构建产出不同。
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
