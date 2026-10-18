FROM node:24-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . ./
RUN npm run build

EXPOSE 3000

ENV NEXT_PUBLIC_API_URL=http://localhost:8000

CMD ["npm", "start"]
