# frontend/Dockerfile

# Stage 1: Build the React app
FROM node:18-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm install
COPY . .
# --- REMOVE THESE LINES ---
# ARG VITE_API_URL
# ENV VITE_API_URL=$VITE_API_URL
# RUN echo "Building frontend with API URL: $VITE_API_URL"
# --- END REMOVAL ---
RUN npm run build

# Stage 2: Serve the static files with Nginx
FROM nginx:1.25-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]