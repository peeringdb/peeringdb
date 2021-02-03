FROM python:3.9-alpine as base

ARG virtual_env=/srv/www.peeringdb.com/venv

ENV VIRTUAL_ENV="$virtual_env"
ENV PATH="$VIRTUAL_ENV/bin:$PATH"


# build container
FROM base as builder

RUN apk --update --no-cache add \
  g++ \
  libjpeg-turbo-dev \
  linux-headers \
  make \
  mariadb-dev \
  libffi-dev

# create venv
RUN pip install -U pip pipenv
RUN python3 -m venv "$VIRTUAL_ENV"

WORKDIR /srv/www.peeringdb.com
ADD Pipfile* ./
RUN pipenv install --ignore-pipfile

# inetd
RUN apk add busybox-extras


#### final image here

FROM base as final

ARG uid=996

# extra settings file if needed
ARG ADD_SETTINGS_FILE=mainsite/settings/dev.py

# add dependencies
RUN apk add gettext libjpeg-turbo mariadb-connector-c

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
# copy from builder in case we're testing new deps
COPY --from=builder /srv/www.peeringdb.com/Pipfile* ./
RUN true
COPY tests/ tests
RUN chown -R pdb:pdb tests/
COPY Ctl/docker/entrypoint.sh .

RUN pip install -U pipenv
RUN pipenv install --dev --ignore-pipfile -v
#RUN echo `which python`
#RUN pip freeze
#RUN pytest -v -rA --cov-report term-missing --cov=peeringdb_server tests/

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
