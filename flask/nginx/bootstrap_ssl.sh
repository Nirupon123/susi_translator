#!/bin/sh
set -e

if [ -z "$DOMAIN_NAME" ]; then
    echo "Error: DOMAIN_NAME environment variable is not set."
    exit 1
fi

CERT_DIR="/etc/letsencrypt/live/susi"
CERT_KEY="${CERT_DIR}/privkey.pem"
CERT_CRT="${CERT_DIR}/fullchain.pem"

mkdir -p "$CERT_DIR"

if [ ! -f "$CERT_CRT" ] || [ ! -f "$CERT_KEY" ]; then
    echo "Let's Encrypt certificates not found. Generating temporary dummy certificates to bootstrap Nginx..."
    openssl req -x509 -nodes -days 1 -newkey rsa:2048 \
        -keyout "$CERT_KEY" \
        -out "$CERT_CRT" \
        -subj "/CN=${DOMAIN_NAME}"
    echo "Dummy certificates generated successfully!"
else
    echo "Certificates found at ${CERT_DIR}. Skipping bootstrap."
fi

# Start a background process to gracefully reload Nginx every 6 hours
# This ensures that when Certbot renews the certificate, Nginx will pick it up automatically
(
    while :; do
        sleep 6h
        echo "Auto-reloading Nginx to pick up any renewed SSL certificates..."
        nginx -s reload
    done
) &
