# syntax=docker/dockerfile:1

# Stage 1: Build Flutter Web application
FROM ghcr.io/cirruslabs/flutter:stable AS builder

WORKDIR /app

# Pre-cache dependencies
COPY pubspec.yaml pubspec.lock ./
RUN flutter pub get

# Copy the rest of the application code
COPY . .

# Ensure .env exists so Flutter asset bundling succeeds during build.
# If .env does not exist, copy .env.example as a fallback.
RUN if [ ! -f .env ]; then cp .env.example .env; fi

# Build production web bundle
RUN flutter build web --release

# Stage 2: Serve with NGINX
FROM nginx:alpine AS runner

# Remove default nginx html files
RUN rm -rf /usr/share/nginx/html/*

# Copy built web artifacts from builder
COPY --from=builder /app/build/web /usr/share/nginx/html

# Copy custom nginx configuration template (processed by official nginx envsubst)
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Copy runtime environment generator hook into nginx docker-entrypoint.d
COPY docker-entrypoint.sh /docker-entrypoint.d/40-generate-env.sh
RUN chmod +x /docker-entrypoint.d/40-generate-env.sh

# Default web hosting port and proxy destinations
ENV WEB_PORT=80 \
    BACKEND_HOST=server \
    BACKEND_PORT=8000

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
