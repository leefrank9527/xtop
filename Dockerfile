FROM ubuntu:24.04
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    sudo supervisor nginx dos2unix \
    linux-libc-dev gcc python3-dev \
    python3-venv


WORKDIR /deployment
COPY monitor/ ./monitor
COPY main.py ./
COPY requirements.txt ./

# Create a virtual environment
RUN python3 -m venv --system-site-packages /deployment/.venv

# Activate the virtual environment and install Python packages
ENV PATH="/deployment/.venv/bin:$PATH"
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r ./requirements.txt

CMD ["python3", "main.py"]
