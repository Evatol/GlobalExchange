FROM python:3.13-slim

# libpq: cliente nativo que necesita psycopg para hablar con Postgres.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
# sed -i 's/\r$//': por las dudas Git en Windows haya convertido el
# archivo a CRLF al clonar (rompe el shebang #!/bin/sh dentro del
# contenedor Linux con "no such file or directory"), sin importar
# .gitattributes.
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
