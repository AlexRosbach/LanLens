FROM alpine:3.20

RUN apk add --no-cache ca-certificates iproute2 nmap python3

WORKDIR /app
COPY scan_node.py /app/scan_node.py

ENV LANLENS_SCAN_INTERVAL=300

CMD ["python3", "/app/scan_node.py"]
