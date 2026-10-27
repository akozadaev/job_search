#!/usr/bin/env python3
"""
Миграция текущих папок с откликами в единый registry.yaml.

Использование:
    python scripts/migrate.py [--dry-run] [--force]

Флаги:
    --dry-run   Только показать, что будет сделано (без изменений)
    --force     Перезаписать существующий registry.yaml
"""

import argparse
import os
import tempfile
import re
import sys
import yaml
from pathlib import Path
from datetime import date

BASE_DIR = Path(__file__).parent.parent
REGISTRY_FILE = BASE_DIR / "registry.yaml"

# Паттерны для парсинга имён папок
DATE_PATTERN_LEFT = re.compile(r"^(\d{4})[.\-](\d{2})[.\-](\d{2})[\s_]+(.+)$")
DATE_PATTERN_RIGHT = re.compile(r"^(.+?)\s+(\d{2})[.\-](\d{2})[.\-](\d{2})$")
STATUS_PATTERN = re.compile(r"\s*[-–—]\s*(Отказ|Отказано|Rejected|Отмена|Archived)$", re.IGNORECASE)


def parse_folder_name(folder_name: str) -> dict:
    """Парсит имя папки и извлекает дату, компанию и статус."""
    result = {
        "company": folder_name,
        "date": None,
        "status": "applied",
        "notes": ""
    }

    # Убираем статус из имени
    status_match = STATUS_PATTERN.search(folder_name)
    if status_match:
        status_text = status_match.group(1).lower()
        result["notes"] = f"Статус: {status_match.group(1)}"
        folder_name = STATUS_PATTERN.sub("", folder_name).strip()

        if "отказ" in status_text or "rejected" in status_text:
            result["status"] = "rejected"
        elif "отмена" in status_text or "archived" in status_text:
            result["status"] = "archived"

    # Дата в начале: 2026.10.16 Компания или 2026-10-16 Компания
    match = DATE_PATTERN_LEFT.match(folder_name)
    if match:
        year, month, day, company = match.groups()
        result["date"] = date(int(year), int(month), int(day)).isoformat()
        result["company"] = company.strip()
        return result

    # Дата в конце: Компания 20.09.26
    match = DATE_PATTERN_RIGHT.match(folder_name)
    if match:
        company, day, month, year_short = match.groups()
        year = f"20{year_short}" if len(year_short) == 2 else year_short
        result["date"] = date(int(year), int(month), int(day)).isoformat()
        result["company"] = company.strip()
        return result

    # Дату не нашли
    raise ValueError(f"Не удалось определить дату из имени папки: {folder_name}")


def read_cover_letter(folder: Path) -> str:
    """Читает файл сопроводительного письма из папки."""
    # Пробуем разные варианты имён
    candidates = [
        folder / "Сопроводительное",
        folder / "Сопроводительное.txt",
        folder / "cover_letter.txt",
        folder / "cover_letter",
    ]
    for f in candidates:
        if f.is_file():
            for encoding in ["utf-8", "cp1251", "latin-1"]:
                try:
                    return f.read_text(encoding="utf-8-sig" if encoding == "utf-8" else encoding)
                except (UnicodeDecodeError, UnicodeError):
                    continue

    # Ищем файлы с опечатками в имени (Сопроводительноею, сопроводительное и т.д.)
    for f in sorted(folder.iterdir()):
        if f.is_file() and "сопров" in f.name.lower():
            for encoding in ["utf-8", "cp1251", "latin-1"]:
                try:
                    return f.read_text(encoding="utf-8-sig" if encoding == "utf-8" else encoding)
                except (UnicodeDecodeError, UnicodeError):
                    continue

    return ""


def read_vacancy_info(folder: Path) -> dict:
    """Читает файл с информацией о вакансии, если есть."""
    info = {"url": "", "description": "", "stack": []}
    vacancy_file = folder / "Вакансия.txt"
    if not vacancy_file.exists():
        return info

    try:
        content = vacancy_file.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            content = vacancy_file.read_text(encoding="cp1251")
        except UnicodeDecodeError:
            try:
                content = vacancy_file.read_text(encoding="latin-1")
            except UnicodeDecodeError:
                return info

    info["description"] = content

    # Извлекаем именно ссылку на вакансию hh.ru.
    url_match = re.search(r"https?://(?:[\w-]+\.)?hh\.ru/vacancy/\d+(?:[^\s<>\"]*)?", content)
    if url_match:
        info["url"] = url_match.group(0)

    # Ищем ключевые слова стека
    known_tech = [
        "Go", "Golang", "Python", "Java", "TypeScript", "JavaScript",
        "PostgreSQL", "MySQL", "Redis", "Docker", "Kubernetes",
        "Kafka", "RabbitMQ", "NATS", "Elasticsearch", "OpenSearch",
        "ClickHouse", "GraphQL", "gRPC", "REST", "GitLab CI", "GitHub Actions",
        "Prometheus", "Grafana", "OpenTelemetry", "Sentry", "AWS", "GCP", "Azure",
        "Nginx", "Apache", "Terraform", "Ansible", "Helm", "Vault", "NATS JetStream",
        "Valkey", "sqlc", "GORM", "Chi", "Gin", "OAuth2", "mTLS", "Casbin"
    ]
    content_lower = content.lower()
    for tech in known_tech:
        if re.search(r"(?<!\w)" + re.escape(tech.lower()) + r"(?!\w)", content_lower):
            info["stack"].append(tech)

    return info


def migrate(dry_run: bool = False, force: bool = False):
    """Основная функция миграции."""
    if REGISTRY_FILE.exists() and not force:
        print("registry.yaml уже существует. Используйте --force для перезаписи.")
        return

    registry = {"vacancies": []}
    vacancies = registry["vacancies"]
    next_id = 1

    excluded_dirs = {"templates", "output", "scripts", "tests", "tmp", "Отказы"}
    letter_names = {"Сопроводительное", "Сопроводительное.txt",
                    "cover_letter.txt", "cover_letter", "Вакансия.txt"}
    folders = []
    for folder in sorted(BASE_DIR.iterdir()):
        if (not folder.is_dir() or folder.is_symlink()
                or folder.name in excluded_dirs or folder.name.startswith(".")):
            continue
        dated = DATE_PATTERN_LEFT.match(folder.name) or DATE_PATTERN_RIGHT.match(folder.name)
        has_source = any(
            file.is_file() and (file.name in letter_names or "сопров" in file.name.lower())
            for file in folder.iterdir()
        )
        if dated or has_source:
            folders.append(folder)

    if not folders:
        print("Папок для миграции не найдено. Реестр не изменён.")
        return

    print(f"Найдено {len(folders)} папок для миграции:\n")

    for folder in sorted(folders):
        parsed = parse_folder_name(folder.name)
        print(f"  [{parsed['date']}] {parsed['company']} ({parsed['status']})")

        # Читаем cover letter
        cover_text = read_cover_letter(folder)

        # Читаем информацию о вакансии
        vacancy_info = read_vacancy_info(folder)

        # Создаём запись
        entry = {
            "id": next_id,
            "date": parsed["date"],
            "company": parsed["company"],
            "vacancy": "",
            "hh_url": vacancy_info["url"],
            "status": parsed["status"],
            "location": "remote",
            "stack": vacancy_info["stack"][:10],
            "cover_letter_template": "default",
            "cover_letter_raw": cover_text,
            "notes": parsed["notes"]
        }

        # Извлекаем название вакансии из текста cover letter
        if cover_text:
            name = ""
            # Ищем "ваканс(ию|ия) [название]" — ищем после слов-маркеров
            vacancy_match = re.search(
                r"(?:интересовала|откликаюсь|хочу присоединиться|подаю заявку)\s+(?:на\s+)?ваканс(ию|ия)\s+([^.!,\n:]{5,80})",
                cover_text, re.IGNORECASE
            )
            if not vacancy_match:
                vacancy_match = re.search(
                    r"ваканс(ию|ия)\s+([^.!,\n:]{5,80})", cover_text, re.IGNORECASE
                )
            if vacancy_match:
                name = vacancy_match.group(2).strip()
                # Исключаем фразы типа "вакансия предполагает офис"
                if re.match(r'^(?:предполагает|требует|ожидает|содержит)\s+', name, re.IGNORECASE):
                    name = ""
                    # Если нашли "вакансия предполагает", пробуем fallback
                    if not name:
                        fallback_match = re.search(
                            r'(?:в\s+роли|на\s+позицию)\s+([^.!,\n:]{5,80})', cover_text, re.IGNORECASE
                        )
                        if fallback_match:
                            name = fallback_match.group(1).strip()
            else:
                # Fallback: ищем "в роли [должность]" или "на позицию [должность]"
                fallback_match = re.search(
                    r'(?:в\s+роли|на\s+позицию)\s+([^.!,\n:]{5,80})', cover_text, re.IGNORECASE
                )
                if fallback_match:
                    name = fallback_match.group(1).strip()

            if name:
                # Убираем предлоги и союзы в конце
                name = re.sub(r'\s+(?:в|на|для|с|по|о|об|обо)\s+[^,\.!\n:]+$', '', name)
                entry["vacancy"] = name

        # Если vacancy всё ещё пустая — попробуем из файла вакансии
        if not entry["vacancy"]:
            vcontent = vacancy_info["description"]
            v_match = re.search(
                r"(?:вакансия|позиция|название)\s*[:\-]?\s*([^.!\n]{5,80})",
                vcontent, re.IGNORECASE,
            )
            if v_match:
                entry["vacancy"] = v_match.group(1).strip()

        vacancies.append(entry)
        next_id += 1

    if not dry_run:
        save_registry(registry)
        print(f"\nМиграция завершена! Создан {REGISTRY_FILE}")
        print(f"  Записей: {len(vacancies)}")
    else:
        print(f"\n  (dry-run) Было бы создано {len(vacancies)} записей")

    return registry


def save_registry(registry: dict) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=REGISTRY_FILE.parent,
            prefix=f".{REGISTRY_FILE.name}.", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(registry, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, REGISTRY_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        migrate(dry_run=args.dry_run, force=args.force)
    except (OSError, ValueError, yaml.YAMLError) as error:
        parser.exit(1, f"Ошибка: {error}\n")


if __name__ == "__main__":
    main()
