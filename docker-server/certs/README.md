TLS certificates for the HTTPS reverse proxy live here.
They are never committed (*.pem is ignored); this file only keeps the
directory present, because docker-compose bind-mounts it and refuses to
start a container whose mount source does not exist.
