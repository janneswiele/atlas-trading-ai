FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py engine.py ./
ENV STREAMLIT_SERVER_ADDRESS=0.0.0.0
ENV STREAMLIT_SERVER_PORT=8501
ENV ATLAS_DB_PATH=/data/atlas_trading.db
RUN mkdir -p /data
EXPOSE 8501
CMD ["streamlit", "run", "app.py", "--server.headless=true"]
