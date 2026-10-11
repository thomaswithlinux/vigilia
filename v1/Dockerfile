# Image de DEMONSTRATION (reseau fictif). Pour la production, preferez l'installation systemd (deploy/install.sh).
FROM python:3.13-slim

RUN pip install --no-cache-dir "paramiko>=3.4,<5" \
    && useradd --system --home-dir /app --shell /usr/sbin/nologin vigilia \
    && mkdir /app /data && chown vigilia:vigilia /data

WORKDIR /app
COPY server.py live.py demo.py db.py auth.py hints.py adduser.py ./
COPY web ./web

ENV VIGILIA_DATA=/data PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER vigilia
VOLUME /data
EXPOSE 8090

# --allow-http : demonstration uniquement. En production : --cert/--key (HTTPS), voir docs/INSTALLATION.md.
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8090", "--allow-http"]
