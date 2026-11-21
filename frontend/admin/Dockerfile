# syntax=docker/dockerfile:1

# Stage 1: Build Flutter Web application
# Pinned: cirruslabs stopped publishing after 3.44.0 (its `stable` tag is 3.44.0, May 2026),
# while CI runs 3.47.5. See docs/OPERATIONS.md "Frontend Admin Web Hosting & Deployment".
FROM ghcr.io/cirruslabs/flutter:3.44.0 AS builder

WORKDIR /app

# Pre-cache dependencies
COPY pubspec.yaml pubspec.lock ./
RUN flutter pub get

# Copy the rest of the application code
COPY . .

# .env is excluded by .dockerignore: the bundled asset is only a placeholder, because
# docker-entrypoint.sh writes assets/.env at container start.
# Copy .env.example so Flutter asset bundling succeeds.
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
