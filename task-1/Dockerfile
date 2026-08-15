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
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

COPY task-1/src ${LAMBDA_TASK_ROOT}/src

CMD ["src.api.handler"]
