#!/usr/bin/env python3
"""
Генерация сопроводительных писем, управление статусами, дашборд.

Использование:
    python3 scripts/generate.py --list                           # Все записи
    python3 scripts/generate.py <id>                             # Сгенерировать cover letter
    python3 scripts/generate.py --all                            # Сгенерировать для всех applied
    python3 scripts/generate.py --generate --filter-status applied  # Сгенерировать по статусу (applied, interview, offered, rejected, archived)
    python3 scripts/generate.py --status <id> <новый_статус>     # Изменить статус
    python3 scripts/generate.py --dashboard                      # Показать дашборд
    python3 scripts/generate.py --dashboard --save               # Сохранить дашборд в файл

Статусы: draft, applied, interview, offered, rejected, archived
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml
from jinja2 import Environment

BASE_DIR = Path(__file__).parent.parent
REGISTRY_FILE = BASE_DIR / "registry.yaml"
TEMPLATE_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output" / "cover_letters"

VALID_STATUSES = ["draft", "applied", "interview", "offered", "rejected", "archived"]


def load_registry() -> dict:
    """Загружает registry.yaml."""
    if not REGISTRY_FILE.exists():
        print("registry.yaml не найден. Сначала запустите migrate.py")
        sys.exit(1)
    with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return validate_registry(data)


def validate_registry(data: dict) -> dict:
    """Проверяет поля, используемые командами, и нормализует даты и null."""
    if not isinstance(data, dict) or not isinstance(data.get("vacancies"), list):
        raise ValueError("registry.yaml: ожидается объект с массивом vacancies")
    seen = set()
    for index, vacancy in enumerate(data["vacancies"], 1):
        label = f"registry.yaml: запись №{index}"
        if not isinstance(vacancy, dict):
            raise ValueError(f"{label}: ожидается объект")
        entry_id = vacancy.get("id")
        if type(entry_id) is not int or entry_id <= 0 or entry_id in seen:
            raise ValueError(f"{label}: id должен быть положительным и уникальным")
        seen.add(entry_id)
        label += f" (id={entry_id})"
        value = vacancy.get("date")
        if type(value) is date:
            value = value.isoformat()
        try:
            if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError
            date.fromisoformat(value)
        except ValueError:
            raise ValueError(f"{label}: date должна быть датой YYYY-MM-DD") from None
        vacancy["date"] = value
        if not isinstance(vacancy.get("company"), str) or not vacancy["company"].strip():
            raise ValueError(f"{label}: company должна быть непустой строкой")
        if vacancy.get("status") not in VALID_STATUSES:
            raise ValueError(f"{label}: неизвестный status")
        for field in ("vacancy", "hh_url", "location", "notes", "cover_letter_raw",
                      "custom_body", "custom_location_note", "custom_projects_body"):
            if vacancy.get(field) is None:
                vacancy[field] = ""
            elif not isinstance(vacancy[field], str):
                raise ValueError(f"{label}: {field} должно быть строкой")
        if vacancy.get("stack") is None:
            vacancy["stack"] = []
        if not isinstance(vacancy["stack"], list) or not all(
            isinstance(item, str) for item in vacancy["stack"]
        ):
            raise ValueError(f"{label}: stack должен быть массивом строк")
    return data


def save_registry(data: dict) -> None:
    """Заменяет реестр только после успешной записи временного файла."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=REGISTRY_FILE.parent,
            prefix=f".{REGISTRY_FILE.name}.", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, REGISTRY_FILE)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def generate_cover_letter(vacancy: dict) -> str:
    """Генерирует текст cover letter из шаблона или использует сохранённый raw текст."""
    raw_text = vacancy.get("cover_letter_raw", "").strip()

    # Если есть сохранённый raw текст — используем его целиком
    if raw_text:
        return raw_text

    # Иначе генерируем из шаблона
    template_path = TEMPLATE_DIR / "cover_letter.md.j2"
    if not template_path.exists():
        print(f"Шаблон не найден: {template_path}")
        sys.exit(1)

    template_text = template_path.read_text(encoding="utf-8")

    custom_intro = ""
    if vacancy.get("vacancy"):
        custom_intro = f" {vacancy['vacancy']}."

    # Кастомные поля — подменяют только эти части шаблона
    custom_body = vacancy.get("custom_body", "").strip()
    custom_location_note = vacancy.get("custom_location_note", "").strip()
    custom_projects_body = vacancy.get("custom_projects_body", "").strip()

    location_note = ""
    if custom_location_note:
        location_note = custom_location_note
    elif vacancy.get("location") and vacancy["location"] != "remote":
        location_note = f" Рассмотрю формат: {vacancy['location']}."
    elif vacancy.get("notes") and "офис" in vacancy.get("notes", "").lower():
        location_note = " Рассмотрю удалённый формат работы."

    context = {
        "company": vacancy.get("company", "Компания"),
        "vacancy": vacancy.get("vacancy", "вакансию"),
        "custom_intro": custom_intro,
        "custom_body": custom_body,
        "custom_projects_body": custom_projects_body,
        "location_note": location_note
    }

    env = Environment(
        variable_start_string="{{",
        variable_end_string="}}",
        block_start_string="{#",
        block_end_string="#}",
        comment_start_string="{*",
        comment_end_string="*}",
    )
    template = env.from_string(template_text)
    return template.render(**context)


def cmd_list(data: dict):
    """Показывает все записи."""
    vacancies = data.get("vacancies", [])
    if not vacancies:
        print("Записей не найдено.")
        return

    print(f"\n{'ID':<4} {'Дата':<12} {'Компания':<20} {'Вакансия':<30} {'Статус':<12}")
    print("-" * 78)
    for v in vacancies:
        print(
            f"{v['id']:<4} "
            f"{v['date']:<12} "
            f"{v['company']:<20} "
            f"{v.get('vacancy', '-'):<30} "
            f"{v['status']:<12}"
        )
    print(f"\nВсего: {len(vacancies)}\n")


def cmd_generate(data: dict, target_id: int | None = None,
                 status_filter: str | None = None) -> None:
    """Генерирует cover letter для одной или нескольких записей."""
    vacancies = data.get("vacancies", [])
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if target_id is not None:
        target = next((v for v in vacancies if v["id"] == target_id), None)
        if not target:
            raise ValueError(f"Запись с id={target_id} не найдена.")
        vacancies = [target]

    if status_filter:
        vacancies = [v for v in vacancies if v["status"] == status_filter]

    if not vacancies:
        print("Нет записей для генерации.")
        return

    for v in vacancies:
        text = generate_cover_letter(v)
        company = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", v["company"])
        company = company.strip(" .")[:120] or "company"
        filename = f"{v['date']}_{v['id']}_{company}.txt"
        filepath = OUTPUT_DIR / filename

        filepath.write_text(text, encoding="utf-8")

        status_icon = {"applied": "✓", "interview": "🔵", "rejected": "✗", "offered": "★", "archived": "○"}.get(v["status"], "?")
        print(f"  {status_icon} [{v['id']}] {v['company']} -> {filepath.name}")

    print(f"\nСгенерировано: {len(vacancies)}")
    print(f"Сохранено в: {OUTPUT_DIR}")


def cmd_status(data: dict, target_id: int, new_status: str):
    """Изменяет статус записи."""
    if new_status not in VALID_STATUSES:
        print(f"Неверный статус. Доступные: {', '.join(VALID_STATUSES)}")
        sys.exit(1)

    vacancies = data.get("vacancies", [])
    target = next((v for v in vacancies if v["id"] == target_id), None)
    if not target:
        raise ValueError(f"Запись с id={target_id} не найдена.")

    old_status = target["status"]
    target["status"] = new_status
    save_registry(data)

    status_icons = {
        "applied": "✓", "interview": "🔵", "offered": "★",
        "rejected": "✗", "archived": "○"
    }
    icon = status_icons.get(new_status, "?")
    print(f"  {icon} [{target_id}] {target['company']}: {old_status} -> {new_status}")


def cmd_dashboard(data: dict, save: bool = False):
    """Показывает или генерирует дашборд."""
    vacancies = data.get("vacancies", [])
    if not vacancies:
        print("Записей не найдено.")
        return

    # Статистика
    stats = {}
    for v in vacancies:
        s = v["status"]
        stats[s] = stats.get(s, 0) + 1

    # Сортируем по дате (новые сверху)
    sorted_vacancies = sorted(vacancies, key=lambda x: x["date"], reverse=True)

    # Статусы для отображения
    status_labels = {
        "draft": "draft",
        "applied": "applied",
        "interview": "interview",
        "offered": "offered",
        "rejected": "rejected",
        "archived": "archived"
    }

    lines = []
    lines.append("# Дашборд откликов")
    lines.append("")
    lines.append(f"**Всего откликов:** {len(vacancies)}")
    lines.append("")
    for s in VALID_STATUSES:
        count = stats.get(s, 0)
        if count > 0:
            label = status_labels[s]
            lines.append(f"- **{label}:** {count}")
    lines.append("")
    lines.append("| Дата | Компания | Вакансия | Статус | Стек |")
    lines.append("|------|----------|----------|--------|------|")

    for v in sorted_vacancies:
        stack = ", ".join(v.get("stack", [])[:3]) if v.get("stack") else "-"
        vacancy = v.get("vacancy", "-")
        lines.append(
            f"| {v['date']} | {v['company']} | {vacancy} | {v['status']} | {stack} |"
        )

    lines.append("")

    # Добавляем раздел с деталями по каждой вакансии
    lines.append("---")
    lines.append("")
    lines.append("# Детали по откликам")
    lines.append("")

    for v in sorted_vacancies:
        lines.append(f"## {v['company']} — {v.get('vacancy', 'N/A')}")
        lines.append("")
        lines.append(f"- **Дата:** {v['date']}")
        lines.append(f"- **Статус:** {v['status']}")
        if v.get("hh_url"):
            lines.append(f"- **Ссылка:** {v['hh_url']}")
        if v.get("location"):
            lines.append(f"- **Локация:** {v['location']}")
        if v.get("stack"):
            lines.append(f"- **Стек:** {', '.join(v['stack'])}")
        if v.get("notes"):
            lines.append(f"- **Примечания:** {v['notes']}")
        lines.append("")

    dashboard_text = "\n".join(lines)

    print(dashboard_text)

    if save:
        output_path = BASE_DIR / "output" / "dashboard.md"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(dashboard_text, encoding="utf-8")
        print(f"\nДашборд сохранён в: {output_path}")


def positive_id(value: str) -> int:
    try:
        result = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("ID должен быть положительным числом") from None
    if result <= 0:
        raise argparse.ArgumentTypeError("ID должен быть положительным числом")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("id", nargs="?", type=positive_id)
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument("--list", action="store_true")
    commands.add_argument("--dashboard", action="store_true")
    commands.add_argument("--edit", action="store_true")
    commands.add_argument("--status", nargs=2, metavar=("ID", "STATUS"))
    commands.add_argument("--generate", "-g", action="store_true")
    commands.add_argument("--all", action="store_true", help="Генерация для applied")
    parser.add_argument("--filter-status", choices=VALID_STATUSES)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    if len(sys.argv) == 1:
        parser.print_help()
        return
    if args.id is not None and any((args.list, args.dashboard, args.edit, args.status, args.all)):
        parser.error("ID можно использовать только для генерации")
    if args.filter_status and not (args.generate or args.id is not None):
        parser.error("--filter-status требует --generate или ID")
    if args.save and not args.dashboard:
        parser.error("--save требует --dashboard")
    if args.status:
        try:
            status_id = positive_id(args.status[0])
        except argparse.ArgumentTypeError as error:
            parser.error(str(error))
        if args.status[1] not in VALID_STATUSES:
            parser.error(f"Доступные статусы: {', '.join(VALID_STATUSES)}")
    if not any((args.list, args.dashboard, args.edit, args.status, args.generate,
                args.all, args.id is not None)):
        parser.error("Укажите команду или ID")
    try:
        data = load_registry()
        if args.list:
            cmd_list(data)
        elif args.dashboard:
            cmd_dashboard(data, save=args.save)
        elif args.edit:
            editor = os.environ.get("EDITOR", "nano")
            subprocess.run([editor, str(REGISTRY_FILE)], check=True)
            cmd_list(load_registry())
        elif args.status:
            cmd_status(data, status_id, args.status[1])
        else:
            cmd_generate(data, target_id=args.id,
                         status_filter="applied" if args.all else args.filter_status)
    except (OSError, ValueError, yaml.YAMLError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Ошибка: {error}\n")


if __name__ == "__main__":
    main()
