.PHONY: install download-history train run-bot run-dashboard run-testnet setup lint clean run-api

# Instalar dependencias
install:
	pip install -r requirements.txt

# Baixar dados historicos (3 anos por padrao)
download-history:
	python scripts/download_history.py --anos 3

# Treinar modelo com dados existentes
train:
	python scripts/train_model.py

# Treinar modelo a partir de CSVs
train-csv:
	python scripts/train_model.py --from-csv

# Rodar o bot (modo configurado no .env)
run-bot:
	python main.py

# Rodar dashboard Streamlit
run-dashboard:
	streamlit run dashboard/app.py

# Rodar bot em modo testnet (sobrescreve .env)
run-testnet:
	BINANCE_TESTNET=true python main.py

# Rodar bot em modo producao (sobrescreve .env)
run-prod:
	BINANCE_TESTNET=false python main.py

# Setup completo: instalar + baixar dados + treinar
setup: install download-history train

# Criar banco de dados (tabelas + hypertables)
init-db:
	python database.py

# Limpar modelos e logs
clean:
	rm -rf models/scalping_model_v*.pkl
	rm -rf logs/bot_*.log
	rm -rf __pycache__ core/__pycache__ scripts/__pycache__

# Rodar API FastAPI
run-api:
	uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Ajuda
help:
	@echo "Comandos disponiveis:"
	@echo "  make install          - Instalar dependencias"
	@echo "  make download-history - Baixar dados historicos (3 anos)"
	@echo "  make train            - Treinar modelo"
	@echo "  make train-csv        - Treinar modelo a partir de CSVs"
	@echo "  make run-bot          - Rodar bot"
	@echo "  make run-testnet      - Rodar bot em testnet"
	@echo "  make run-prod         - Rodar bot em producao"
	@echo "  make run-dashboard    - Rodar dashboard Streamlit"
	@echo "  make setup            - Setup completo (install + download + train)"
	@echo "  make init-db          - Criar tabelas no banco"
	@echo "  make run-api          - Rodar API FastAPI"
	@echo "  make clean            - Limpar modelos e logs"
