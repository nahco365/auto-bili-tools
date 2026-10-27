FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
COPY python_port/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY bili_qinglong.py bili_medal.py bili_login.py bili_device.py qrcodegen.py gaia_template.json /app/
COPY python_port /app/python_port
ENV PYTHONUNBUFFERED=1 BILI_PY_HOST=0.0.0.0 BILI_PY_PORT=8080 BILI_PY_DB=/app/data/bilitool.sqlite TZ=Asia/Shanghai
VOLUME ["/app/data"]
EXPOSE 8080
CMD ["python", "-m", "python_port.server"]
