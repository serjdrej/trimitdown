#!/bin/sh
# Prepare the local Docker-server directory without replacing its credentials.

set -eu
umask 077

usage() {
    echo "Usage: $0 SERVER_ADDRESS" >&2
    echo "SERVER_ADDRESS must be the server IP address or hostname." >&2
    exit 1
}

fail() {
    echo "setup.sh: $*" >&2
    exit 1
}

[ "$#" -eq 1 ] || usage

server_address=$1
case "$server_address" in
    *[!A-Za-z0-9.:_-]* | '')
        fail "SERVER_ADDRESS must be an IP address or hostname."
        ;;
esac

command -v openssl >/dev/null 2>&1 || \
    fail "OpenSSL is required to create a certificate and token."

mkdir -p certs archive

case "$server_address" in
    *:*) subject_alt_name="IP:$server_address" ;;
    *[!0-9.]*) subject_alt_name="DNS:$server_address" ;;
    *) subject_alt_name="IP:$server_address" ;;
esac

create_certificate() {
    certificate_mode=$1

    if openssl req -help 2>&1 | grep -q -- '-addext'; then
        if [ "$certificate_mode" = pair ]; then
            openssl req -x509 -nodes -newkey rsa:2048 \
                -keyout certs/key.pem -out certs/cert.pem -days 3650 \
                -subj "/CN=$server_address" \
                -addext "subjectAltName=$subject_alt_name"
        else
            openssl req -x509 -new -key certs/key.pem \
                -out certs/cert.pem -days 3650 \
                -subj "/CN=$server_address" \
                -addext "subjectAltName=$subject_alt_name"
        fi
        return
    fi

    openssl_config=${TMPDIR:-/tmp}/trimitdown-openssl.$$
    trap 'rm -f "$openssl_config"' 0 1 2 3 15
    printf '%s\n' \
        '[req]' \
        'distinguished_name = distinguished_name' \
        'x509_extensions = v3_req' \
        'prompt = no' \
        '[distinguished_name]' \
        "CN = $server_address" \
        '[v3_req]' \
        "subjectAltName = $subject_alt_name" > "$openssl_config" || \
        fail "Could not create a temporary OpenSSL configuration."

    if [ "$certificate_mode" = pair ]; then
        openssl req -x509 -nodes -newkey rsa:2048 \
            -keyout certs/key.pem -out certs/cert.pem -days 3650 \
            -config "$openssl_config"
    else
        openssl req -x509 -new -key certs/key.pem \
            -out certs/cert.pem -days 3650 -config "$openssl_config"
    fi
}

if [ -f certs/cert.pem ] && [ -f certs/key.pem ]; then
    echo "Certificate and key already exist; keeping them."
elif [ -f certs/cert.pem ]; then
    fail "certs/cert.pem exists but certs/key.pem is missing; restore the matching key or remove the certificate deliberately before retrying."
elif [ -f certs/key.pem ]; then
    echo "Key already exists; creating the missing certificate from it."
    create_certificate key
else
    echo "Creating a self-signed certificate."
    create_certificate pair
fi

if [ -f .env ]; then
    token=$(sed -n 's/^TRIMITDOWN_TOKEN=//p' .env | awk 'NF { print; exit }')
else
    token=
fi

if [ -n "$token" ]; then
    echo "TRIMITDOWN_TOKEN already exists in .env; keeping it."
else
    token=$(openssl rand -hex 24) || fail "OpenSSL could not generate TRIMITDOWN_TOKEN."
    if [ -f .env ]; then
        printf '\nTRIMITDOWN_TOKEN=%s\n' "$token" >> .env
    else
        printf 'TRIMITDOWN_TOKEN=%s\n' "$token" > .env
    fi
    echo "Created TRIMITDOWN_TOKEN in .env."
fi

printf 'Ready: https://%s:8002/?k=%s\n' "$server_address" "$token"
