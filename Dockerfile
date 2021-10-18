# RUN true is used here to separate problematic COPY statements,
# per this issue: https://github.com/moby/moby/issues/37965

FROM python:3.9-alpine as base

ARG virtual_env=/srv/www.peeringdb.com/venv

ENV VIRTUAL_ENV="$virtual_env"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"


# build container
FROM base as builder

# rust and cargo for cryptography package
RUN apk --update --no-cache add \
  g++ \
  freetype-dev \
  libjpeg-turbo-dev \
  linux-headers \
  make \
  mariadb-dev \
  libffi-dev \
  curl \
  rust \
  cargo

RUN pip install -U pip poetry
# create venv and update venv pip
RUN python3 -m venv "$VIRTUAL_ENV" && pip install -U pip

WORKDIR /srv/www.peeringdb.com
COPY poetry.lock pyproject.toml ./
# install dev now so we don't need a build env for testing (adds 8M)
RUN poetry install --no-root

# inetd
RUN apk add busybox-extras

#### final image here

FROM base as final

ARG uid=996

# extra settings file if needed
ARG ADD_SETTINGS_FILE=mainsite/settings/dev.py

# add dependencies
RUN apk add --no-cache freetype ttf-freefont gettext libjpeg-turbo graphviz mariadb-connector-c libgcc

RUN adduser -Du $uid pdb

WORKDIR /srv/www.peeringdb.com
COPY --from=builder "$VIRTUAL_ENV" "$VIRTUAL_ENV"

RUN mkdir -p api-cache etc locale media static var/log
COPY manage.py .
# container exec whois
COPY in.whoisd .
COPY Ctl/VERSION etc
COPY docs/ docs
COPY mainsite/ mainsite
RUN true
COPY $ADD_SETTINGS_FILE mainsite/settings/
RUN true
COPY peeringdb_server/ peeringdb_server
COPY fixtures/ fixtures
COPY .coveragerc .coveragerc
RUN mkdir coverage

COPY scripts/manage /usr/bin/
COPY Ctl/docker/entrypoint.sh /

# inetd for whois
COPY --from=builder /usr/sbin/inetd /usr/sbin/
RUN true
COPY Ctl/docker/inetd.conf /etc/

RUN chown -R pdb:pdb api-cache locale media var/log coverage

#### test image here
FROM final as tester

WORKDIR /srv/www.peeringdb.com
COPY poetry.lock pyproject.toml ./
RUN true
COPY tests/ tests
RUN chown -R pdb:pdb tests/
COPY Ctl/docker/entrypoint.sh .

# install dev deps
RUN pip install -U poetry
RUN poetry install --no-root

USER pdb
ENTRYPOINT ["./entrypoint.sh"]
CMD ["runserver", "$RUNSERVER_BIND"]

#### entry point from final image, not tester
FROM final

COPY Ctl/docker/entrypoint.sh .
RUN true
COPY Ctl/docker/django-uwsgi.ini etc/

ENV UWSGI_SOCKET="127.0.0.1:7002"
ENV RUNSERVER_BIND="127.0.0.1:8080"

USER pdb

ENTRYPOINT ["./entrypoint.sh"]
CMD ["runserver", "$RUNSERVER_BIND"]
