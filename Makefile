.DEFAULT_GOAL := help
.PHONY: help install run test lint format _check.uv \
        db.new db.up db.up.one db.down db.down.to db.history db.current db.reset \
        compose.up compose.down compose.logs

# 색상
CYAN := \033[36m
RESET := \033[0m

help:  ## 사용 가능한 명령어
	@echo "사용법: make <target>"
	@echo ""
	@grep -E '^[a-zA-Z_.-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  $(CYAN)%-15s$(RESET) %s\n", $$1, $$2}'
	@echo ""
	@echo "DB 마이그레이션 추가 인자:"
	@echo "  $(CYAN)make db.new name=add_users_table$(RESET)"
	@echo "  $(CYAN)make db.down.to rev=abc123$(RESET)"

# uv 설치 안내 (https://docs.astral.sh/uv/)
_check.uv:
	@command -v uv >/dev/null 2>&1 || { \
		echo "uv가 설치되지 않았어. 설치: curl -LsSf https://astral.sh/uv/install.sh | sh"; \
		exit 1; \
	}

install: _check.uv  ## 의존성 설치 (uv sync)
	uv sync

run: _check.uv  ## 로컬 개발 서버 실행
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test: _check.uv  ## 테스트 실행
	uv run pytest -v

lint: _check.uv  ## ruff 린트
	uv run ruff check app tests

format: _check.uv  ## ruff 포맷
	uv run ruff format app tests

# ==============================================================================
# DB 마이그레이션 (Alembic 래퍼)
# ==============================================================================
db.new: _check.uv  ## 새 마이그레이션 생성. usage: make db.new name=add_users_table
	@if [ -z "$(name)" ]; then echo "usage: make db.new name=<migration_name>"; exit 1; fi
	uv run alembic revision --autogenerate -m "$(name)"

db.up: _check.uv  ## 최신 마이그레이션까지 적용
	uv run alembic upgrade head

db.up.one: _check.uv  ## 한 단계만 적용
	uv run alembic upgrade +1

db.down: _check.uv  ## 한 단계 롤백
	uv run alembic downgrade -1

db.down.to: _check.uv  ## 특정 리비전까지 롤백. usage: make db.down.to rev=abc123
	@if [ -z "$(rev)" ]; then echo "usage: make db.down.to rev=<revision>"; exit 1; fi
	uv run alembic downgrade $(rev)

db.history: _check.uv  ## 마이그레이션 히스토리
	uv run alembic history --verbose

db.current: _check.uv  ## 현재 적용된 리비전
	uv run alembic current

db.reset: _check.uv  ## (개발용) 모든 마이그레이션 롤백
	uv run alembic downgrade base

# ==============================================================================
# Docker Compose
# ==============================================================================
compose.up:  ## docker-compose 백그라운드 시작
	docker compose -f docker/docker-compose.yml --env-file .env up -d

compose.down:  ## docker-compose 정지
	docker compose -f docker/docker-compose.yml down

compose.logs:  ## docker-compose 로그 follow
	docker compose -f docker/docker-compose.yml logs -f
