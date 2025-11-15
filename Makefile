# Resume Agent Makefile

CONDA = /opt/homebrew/Caskroom/miniconda/base/bin/conda
ENV = resume-agent

# Run Flask server
run:
	$(CONDA) run -n $(ENV) --no-capture-output python -m src.api.server

# Run MLflow UI
mlflow:
	MLFLOW_TRUNCATE_LONG_VALUES=false $(CONDA) run -n $(ENV) --no-capture-output mlflow ui --host 0.0.0.0 --port 5001

# Run database migrations
migrate-db:
	$(CONDA) run -n $(ENV) --no-capture-output python -m scripts.migrate_status_db

# Run both (manual split in VS Code)
all:
	@echo "VS Code Instructions:"
	@echo "1. Split terminal: Cmd+\ (or click split terminal icon)"
	@echo "2. Run 'make mlflow' in first terminal"
	@echo "3. Run 'make run' in second terminal"
	@echo ""
	@echo "Or use VS Code tasks (see below)"
	@echo ""
	@echo "Starting server in this terminal..."
	$(CONDA) run -n $(ENV) python -m src.api.server

.PHONY: run mlflow migrate-db all