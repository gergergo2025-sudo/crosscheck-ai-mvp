FROM python:3.11.9-alpine3.20@sha256:f9ce6fe33d9a5499e35c976df16d24ae80f6ef0a28be5433140236c2ca482686
RUN pip install --no-cache-dir pytest==8.3.5
RUN mkdir /work && chown 65534:65534 /work
USER 65534
WORKDIR /work
CMD ["python", "-I", "-B"]
