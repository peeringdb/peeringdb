ARG python_version=3.12

ARG build_deps=" \
    build-essential \
    ca-certificates \
    git \
    pkg-config \
    python3-setuptools \
    python${python_version}-dev \
    libfreetype6-dev \
    libjpeg-turbo8-dev \
    linux-headers-generic \
    libmariadb-dev \
    libffi-dev \
    curl \
    rustc \
    cargo \
    "
ARG run_deps=" \
    python${python_version} \
    libpython${python_version} \
    libpcre3 \
    libxml2 \
    libfreetype6 \
    fonts-freefont-ttf \
    gettext \
    libjpeg-turbo8 \
    graphviz \
    libmariadb3 \
    libgcc-s1 \
    "

FROM ubuntu:24.04 AS base

ARG virtual_env=/srv/www.peeringdb.com/venv
ARG python_version

ENV VIRTUAL_ENV="$virtual_env"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# - Silence uv complaining about not being able to use hard links,
# - tell uv to byte-compile packages for faster application startups,
# - prevent uv from accidentally downloading isolated Python builds,
# - pick a Python,
# - and finally declare `/app` as the target for `uv sync`.
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=python${python_version} \
    UV_PROJECT_ENVIRONMENT=$VIRTUAL_ENV

# base docker file from https://hynek.me/articles/docker-uv/
FROM base AS builder

ARG python_version
ARG build_deps

# The following does not work in Podman unless you build in Docker
# compatibility mode: <https://github.com/containers/podman/issues/8477>
# You can manually prepend every RUN script with `set -ex` too.
SHELL ["sh", "-exc"]

### Start Build Prep.
### This should be a separate build container for better reuse.

RUN <<EOT
apt-get update -qy
apt-get install -qyy \
    -o APT::Install-Recommends=false \
    -o APT::Install-Suggests=false \
    $build_deps
EOT

# Security-conscious organizations should package/review uv themselves.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv


WORKDIR /srv/www.peeringdb.com

# Since there's no point in shipping lock files, we move them
# into a directory that is NOT copied into the runtime image.
# The trailing slash makes COPY create `/_lock/` automagically.

# keep the lock with the image in case we are debugging
COPY uv.lock pyproject.toml ./

RUN uv venv $virtual_env

# Synchronize DEPENDENCIES without the application itself.
# This layer is cached until uv.lock or pyproject.toml change.
# You can create `/app` using `uv venv` in a separate `RUN`
# step to have it cached, but with uv it's so fast, it's not worth
# it, so we let `uv sync` create it for us automagically.

RUN --mount=type=cache,target=/root/.cache <<EOT
uv sync \
    --locked \
    --no-dev \
    --no-install-project
EOT

# Now install the APPLICATION from `/src` without any dependencies.
# `/src` will NOT be copied into the runtime container.
# LEAVE THIS OUT if your application is NOT a proper Python package.
# As of uv 0.4.11, you can also use
# `cd /src && uv sync --locked --no-dev --no-editable` instead.
COPY . /src
RUN cd /src && uv sync --locked --no-dev --no-editable

# COPY . /src
# RUN --mount=type=cache,target=/root/.cache \
#     uv pip install \
#         --python=$UV_PROJECT_ENVIRONMENT \
#         --no-deps \
#         /src



# RUN true is used here to separate problematic COPY statements,
# per this issue: https://github.com/moby/moby/issues/37965



## build container
#FROM base as builder
#
#ARG build_deps
#
#RUN apk --update --no-cache add $build_deps
#
#RUN pip install -U pip poetry
## create venv and update venv pip
#RUN python3 -m venv "$VIRTUAL_ENV" && pip install -U pip
#
#WORKDIR /srv/www.peeringdb.com
#COPY poetry.lock pyproject.toml ./
## install dev now so we don't need a build env for testing (adds 8M)
#RUN poetry install --no-root
#

#### final image here


FROM base as final

ARG run_deps
ARG uid=996

# extra settings file if needed
ARG ADD_SETTINGS_FILE=mainsite/settings/dev.py

SHELL ["sh", "-exc"]

# Don't run your app as root.
RUN <<EOT
groupadd -r pdb
useradd -r -u $uid -g pdb -N pdb
EOT
#RUN adduser -Du $uid pdb


ENTRYPOINT ["/entrypoint"]
# See <https://hynek.me/articles/docker-signals/>.
STOPSIGNAL SIGINT


RUN <<EOT
apt-get update -qy
apt-get install -qyy \
    -o APT::Install-Recommends=false \
    -o APT::Install-Suggests=false \
    $run_deps

apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
EOT

WORKDIR /srv/www.peeringdb.com
RUN mkdir -p api-cache etc locale media static var/log

COPY --from=builder "$VIRTUAL_ENV" "$VIRTUAL_ENV"
COPY Ctl/docker/django-uwsgi.ini etc/
COPY manage.py .
COPY Ctl/VERSION etc
COPY Ctl/docker/entrypoint.sh ./
COPY docs/ docs
COPY mainsite/ mainsite
COPY $ADD_SETTINGS_FILE mainsite/settings/
COPY src/peeringdb_server/ peeringdb_server
COPY fixtures/ fixtures
COPY .coveragerc .coveragerc

RUN mkdir coverage && ln -s srv/www.peeringdb.com/entrypoint.sh /entrypoint

COPY scripts/manage /usr/bin/

COPY --from=builder /usr/local/bin/uv /usr/bin/uv
COPY --from=builder /srv/www.peeringdb.com/uv.lock uv.lock
COPY --from=builder /srv/www.peeringdb.com/pyproject.toml pyproject.toml

RUN SECRET_KEY=no manage collectstatic --no-input

RUN chown -R pdb:pdb api-cache locale media var/log coverage

USER pdb
ENTRYPOINT ["/entrypoint"]
CMD ["runserver"]

#### test image here
FROM final as tester

ARG build_deps

USER root
WORKDIR /srv/www.peeringdb.com
COPY tests/ tests
RUN chown -R pdb:pdb tests/

# install dev deps
RUN <<EOT
apt-get update -qy
apt-get install -qyy \
    -o APT::Install-Recommends=false \
    -o APT::Install-Suggests=false \
    $build_deps

apt-get clean
uv sync --locked --dev --no-install-project
rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
EOT

# Same as final entrypoint for running in dev mode

USER pdb

#### entry point from final image, not tester
FROM final

USER pdb
# Strictly optional, but I like it for introspection of what I've built
# and run a smoke test that the application can, in fact, be imported.
# python -Ic 'import peeringdb_server'
RUN <<EOT
python -V
python -Im site
python -c 'import peeringdb_server'
EOT
