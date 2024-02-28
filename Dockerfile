FROM public.ecr.aws/lambda/python:3.12.2024.01.05.15
COPY main.py ${LAMBDA_TASK_ROOT}
CMD [ "main.handler"]