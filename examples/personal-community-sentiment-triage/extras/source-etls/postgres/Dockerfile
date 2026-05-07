FROM postgres:16

COPY init/01-init.sh /docker-entrypoint-initdb.d/01-init.sh
RUN chmod 644 /docker-entrypoint-initdb.d/01-init.sh
