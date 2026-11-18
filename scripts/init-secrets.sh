#!/bin/sh
# Create secrets/caddy.env with a random LAN password. Safe to run again.
set -eu
cd "$(dirname "$0")/.."
mkdir -p secrets
if [ -f secrets/caddy.env ]; then
    exit 0
fi
password=$(od -An -tx1 -N 12 /dev/urandom | tr -d ' \n')
hash=$(docker run --rm caddy:2 caddy hash-password --plaintext "$password")
# Compose treats $ as interpolation. bcrypt hashes must be stored with $$.
hash=$(printf '%s' "$hash" | sed 's/\$/$$/g')
umask 077
printf 'BASIC_AUTH_USER=carvera\nBASIC_AUTH_HASH=%s\n' "$hash" > secrets/caddy.env
if [ ! -f secrets/tls/cert.pem ]; then
    mkdir -p secrets/tls
    names="DNS:localhost,DNS:$(hostname -s),DNS:$(hostname)"
    for ip in 127.0.0.1 $(hostname -I); do
        names="$names,IP:$ip"
    done
    openssl req -x509 -newkey rsa:2048 -sha256 -days 825 -nodes \
        -keyout secrets/tls/key.pem \
        -out secrets/tls/cert.pem \
        -subj "/CN=$(hostname -s)" \
        -addext "subjectAltName=$names"
fi
echo "LAN login user: carvera"
echo "LAN login password: $password"
echo "Saved secrets/caddy.env. It is not committed."
