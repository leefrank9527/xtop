FROM python:3.10-slim

#RUN apt-get update \
#    && apt-get install -y --no-install-recommends \
#    wget git
#
WORKDIR /xtop/
COPY src/ ./src
COPY pyproject.toml ./
COPY requirements.txt ./
COPY README.md ./
COPY LICENSE ./

#
RUN pip install --upgrade pip
#RUN pip install --no-cache-dir -r requirements.txt
RUN pip install .

#
#
#CMD ["python3", "main.py"]

#RUN pip install --upgrade pip
#RUN pip install --no-cache-dir xtop-cli==1.0.7


CMD ["xtop"]