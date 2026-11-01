FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mcp_slack_client.py db_utils.py ./

VOLUME ["/app/data"]
ENV DB_PATH=/app/data/chat_history.db \
    PYTHONUNBUFFERED=1

# The client reads MCP_SERVER_URL when no URL is passed (an exec-form CMD can't expand variables).
CMD ["python", "mcp_slack_client.py"]
