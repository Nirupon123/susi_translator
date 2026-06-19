#!/bin/sh

# Certbot passes the domain being validated in $CERTBOT_DOMAIN
# and the validation string in $CERTBOT_VALIDATION

if [ -z "$DUCKDNS_TOKEN" ]; then
    echo "Error: DUCKDNS_TOKEN environment variable is not set."
    exit 1
fi

# Extract the subname from CERTBOT_DOMAIN (e.g. 'susi' from 'susi.duckdns.org')
SUBDOMAIN=$(echo "$CERTBOT_DOMAIN" | sed 's/\.duckdns\.org//')

echo "Sending TXT record to DuckDNS for subdomain: $SUBDOMAIN"

# Make the DuckDNS API request to update the TXT record
RESPONSE=$(curl -s "https://www.duckdns.org/update?domains=${SUBDOMAIN}&token=${DUCKDNS_TOKEN}&txt=${CERTBOT_VALIDATION}")

if [ "$RESPONSE" = "OK" ]; then
    echo "Successfully updated DuckDNS TXT record."
else
    echo "Failed to update DuckDNS TXT record. Response: $RESPONSE"
    exit 1
fi

# Wait for DNS propagation
echo "Waiting 30 seconds for DNS propagation..."
sleep 30
