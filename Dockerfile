FROM ubuntu:20.04 AS download

RUN apt-get update; apt-get install -y curl ca-certificates

RUN curl -L https://github.com/traefik/traefik/releases/download/v2.5.6/traefik_v2.5.6_linux_amd64.tar.gz -O

RUN tar xzvf traefik_v2.5.6_linux_amd64.tar.gz

FROM ubuntu:20.04

COPY --from=download traefik /usr/local/bin/traefik

RUN mkdir -p /etc/traefik/

ENTRYPOINT /usr/local/bin/traefik