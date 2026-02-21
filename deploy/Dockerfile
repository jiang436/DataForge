# 后端 Dockerfile
FROM python:3.10-slim

WORKDIR /app

# 安装依赖
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# 复制代码
COPY backend/ ./backend/
COPY data/ ./data/

# 预生成演示数据
RUN python -m backend.db.demo_data

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
