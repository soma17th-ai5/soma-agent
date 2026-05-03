# 파이썬 3.12 슬림 버전 사용
FROM python:3.12-slim

# 작업 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치 (필요한 경우)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Poetry 설치
RUN pip install --no-cache-dir poetry

# 의존성 파일 복사
COPY pyproject.toml ./

# Poetry 설정: 가상환경을 생성하지 않고 시스템 파이썬에 직접 설치
# (도커 컨테이너 자체가 격리된 환경이므로 가상환경이 불필요)
RUN poetry config virtualenvs.create false \
    && poetry install --no-interaction --no-ansi --no-root \
    && pip install "httpx<0.26"

# 프로젝트 소스 코드 복사
COPY . .

# FastAPI 실행 포트 노출
EXPOSE 8080

# Uvicorn을 사용하여 서버 실행
CMD ["uvicorn", "soma_app.main:app", "--host", "0.0.0.0", "--port", "8080"]
