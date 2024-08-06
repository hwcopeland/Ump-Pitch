# Use the official Python image from the Docker Hub
FROM python:3.9-slim

# Install git
RUN apt-get update && apt-get install -y git && apt-get clean

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . .

# Run gunicorn when the container launches
CMD ["gunicorn", "--bind", "0.0.0.0:8686", "mlbpitchprod:create_app()"]