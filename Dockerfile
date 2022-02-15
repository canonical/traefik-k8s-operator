FROM ubuntu:20.04 AS download

ARG traefik_version="2.5.6"

RUN apt-get update; apt-get install -y curl ca-certificates

ENV TRAEFIK_VERSION=${traefik_version}

RUN curl -L -s "https://github.com/traefik/traefik/releases/download/v${TRAEFIK_VERSION}/traefik_v${TRAEFIK_VERSION}_linux_amd64.tar.gz" -o traefik.tgz

RUN tar xzf traefik.tgz

FROM ubuntu:20.04

COPY --from=download traefik /usr/local/bin/traefik

RUN mkdir -p /etc/traefik/

ENTRYPOINT /usr/local/bin/traefik