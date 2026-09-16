FROM golang:1.23-bookworm AS go-builder
WORKDIR /src
COPY go.mod ./
COPY cmd/ ./cmd/
COPY engine/ ./engine/
RUN CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o /out/strategy-lab ./cmd/strategy-lab

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/python \
    STRATEGYLAB_PREBUILT_GO=1 \
    HOME=/tmp
WORKDIR /app
RUN python -m pip install --no-cache-dir 'psycopg[binary]>=3.2,<3.3'
COPY server.py ./
COPY python/ ./python/
COPY web/ ./web/
COPY examples/ ./examples/
COPY --from=go-builder /out/strategy-lab ./bin/strategy-lab
USER 10001:10001
EXPOSE 8765
CMD ["python", "-B", "server.py", "--host", "0.0.0.0", "--port", "8765"]
