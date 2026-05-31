FROM python:3.11-slim

WORKDIR /app

# 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 代码 + 配置
COPY src/ src/
COPY config/ config/
COPY .env .env

# 数据目录
RUN mkdir -p data/sessions

EXPOSE 8000

# 默认启动 FastAPI（上层应用自行替换入口）
CMD ["python", "-m", "uvicorn", "src.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
