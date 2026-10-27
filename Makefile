.PHONY: help migrate migrate-force migrate-dry list generate generate-all generate-rejected status dashboard dashboard-save edit clean install

help: ## Показать справку по командам
	@awk 'BEGIN {FS = ":.*##"; printf "\nИспользование:\n  make <цель>\n\nЦели:\n"} /^[$$()% a-zA-Z_-]+:.*## / {printf "  %-20s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

migrate: ## Мигрировать папки с откликами в registry.yaml
	@python3 scripts/migrate.py

migrate-force: ## Перезаписать registry.yaml (даже если уже существует)
	@python3 scripts/migrate.py --force

migrate-dry: ## Показать, что будет сделано при миграции (без изменений)
	@python3 scripts/migrate.py --dry-run

list: ## Показать все отклики
	@python3 scripts/generate.py --list

generate: ## Сгенерировать cover letter для конкретного id
	@python3 scripts/generate.py $(word 2, $(MAKECMDGOALS))

generate-all: ## Сгенерировать cover letters для всех applied
	@python3 scripts/generate.py --generate --filter-status applied

generate-rejected: ## Сгенерировать cover letters для всех rejected
	@python3 scripts/generate.py --generate --filter-status rejected

status: ## Изменить статус отклика
	@python3 scripts/generate.py --status $(word 2, $(MAKECMDGOALS)) $(word 3, $(MAKECMDGOALS))

dashboard: ## Показать дашборд в терминале
	@python3 scripts/generate.py --dashboard

dashboard-save: ## Сохранить дашборд в output/dashboard.md
	@python3 scripts/generate.py --dashboard --save

edit: ## Открыть registry.yaml в редакторе ($EDITOR)
	@python3 scripts/generate.py --edit

clean: ## Удалить сгенерированные файлы
	@rm -rf output/cover_letters/*

install: ## Установить зависимости
	@pip install -r requirements.txt


# Генерация сопроводительных писем, управление статусами, дашборд.

# Использование:
#     python3 scripts/generate.py --list                           # Все записи
#     python3 scripts/generate.py <id>                             # Сгенерировать cover letter
#     python3 scripts/generate.py --all                            # Сгенерировать для всех applied
#     python3 scripts/generate.py --generate --filter-status applied  # Сгенерировать по статусу (applied, interview, offered, rejected, archived)
#     python3 scripts/generate.py --status <id> <новый_статус>     # Изменить статус
#     python3 scripts/generate.py --dashboard                      # Показать дашборд
#     python3 scripts/generate.py --dashboard --save               # Сохранить дашборд в файл

# Статусы: applied, interview, offered, rejected, archived