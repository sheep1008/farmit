# 개발용 이미지: Vite dev server를 띄운다. 배포용(빌드 + Nginx)은 T03에서 따로 만든다.
FROM node:22.18.0-alpine

WORKDIR /app

# package*.json만 먼저 복사해 의존성 설치 층을 캐시한다 (코드만 바뀌면 npm ci를 다시 하지 않는다)
COPY package.json package-lock.json .npmrc ./
RUN npm ci

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
