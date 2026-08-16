# syntax=docker/dockerfile:1.7
#
# Lambda container image for the CareThread API (Task 1). Same shape as
# fleetpulse/task-9/Dockerfile: AWS's own Lambda Python base image (the
# Lambda Runtime Interface Client), Mangum adapting the FastAPI app in
# src/api.py to the Lambda Invoke event/response shape.
#
# Build from the repo root:
#   docker build -f task-1/Dockerfile -t carethread-api-lambda:latest .

FROM public.ecr.aws/lambda/python:3.12

COPY task-1/requirements.txt ${LAMBDA_TASK_ROOT}/requirements.txt
# --default-timeout raised from pip's 15s default: sentence-transformers
# (Task 3) pulls in torch, a slow connection reading a large wheel in
# 15s chunks can hit pip's per-read timeout well before the download
# itself is anywhere near done.
#
# torch installed first, explicitly from PyTorch's CPU-only wheel
# index: PyPI's default torch build for linux pulls a full CUDA
# toolkit (nvidia-cublas, nvidia-curand, ...), multiple GB of GPU
# libraries a CPU-only Lambda function never uses and can't use (no
# GPU device exists in Lambda). Installing the CPU wheel first
# satisfies sentence-transformers' `torch>=1.11.0` dependency before
# pip ever considers the CUDA build, cutting the image (and this
# build's download time) down dramatically.
RUN pip install --no-cache-dir --default-timeout=180 \
      torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --default-timeout=180 -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY task-1/src ${LAMBDA_TASK_ROOT}/src

CMD ["src.api.handler"]
