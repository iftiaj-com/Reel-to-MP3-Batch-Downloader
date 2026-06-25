FROM python:3.9-slim

# Install ffmpeg and clean up apt caches to keep container small
RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /code

# Copy requirements and install python packages
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt

# Copy all application files
COPY . .

# Run Streamlit on port 7860 (Hugging Face standard port)
CMD ["streamlit", "run", "app.py", "--server.port", "7860", "--server.address", "0.0.0.0"]
