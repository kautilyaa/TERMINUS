FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create volume for database
VOLUME ["/app/data"]

# Set environment for database location
ENV DB_PATH=/app/data/chat_history.db

# Run the bot
CMD ["python", "mcp_slack_client.py", "${MCP_SERVER_URL}"]