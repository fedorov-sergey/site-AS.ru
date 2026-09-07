#!/usr/bin/env python3
"""
Генератор страниц парсеров для сайта analizsmet.ru

Сканирует .py файлы парсеров, извлекает метаданные через ast-парсинг,
генерирует HTML-страницы из шаблонов, каталог и обновляет sitemap.xml.

Использование:
    cd build
    python generate.py

Конфигурация путей — в переменных PARSERS_DIR, SITE_DIR внизу файла.
Шаблоны — в папке build/ (template_parser.html и т.д.).
"""

import ast
import os
import re
import shutil
import json
from datetime import date
from typing import Dict, List, Any
from collections import OrderedDict


# ============================================================
# КОНФИГУРАЦИЯ ПУТЕЙ
# ============================================================

# Директория этого скрипта (build/)
BUILD_DIR = os.path.dirname(os.path.abspath(__file__))

# Путь к папке с .py файлами парсеров========================================ВСТАВИТЬ===============
PARSERS_DIR = r"C:\Users\PC\Desktop\Сайт 260907\parsers Удалить при публикации"

# Путь к папке со скриншотами
PIC_DIR = os.path.join(PARSERS_DIR, "pic")

# Путь к сайту (куда генерировать HTML)========================================ВСТАВИТЬ===============
SITE_DIR = r"C:\Users\PC\Desktop\Сайт 260907"

# Папка для страниц парсеров (относительно SITE_DIR)
PARSERS_OUTPUT_DIR = os.path.join(SITE_DIR, "parsers")

# Домен сайта
DOMAIN = "https://analizsmet.ru"

# Файлы, которые не являются парсерами
SKIP_FILES = {"__init__.py", "base_parser.py"}

# Шаблоны
TEMPLATE_PARSER = os.path.join(BUILD_DIR, "template_parser.html")

# Код счётчика Яндекс Метрики (вставляется в <head> каталога parsers.html)
YANDEX_METRIKA = """<!-- Yandex.Metrika counter -->
    <script type="text/javascript">
        (function(m,e,t,r,i,k,a){
            m[i]=m[i]||function(){(m[i].a=m[i].a||[]).push(arguments)};
            m[i].l=1*new Date();
            for (var j = 0; j < document.scripts.length; j++) {if (document.scripts[j].src === r) { return; }}
            k=e.createElement(t),a=e.getElementsByTagName(t)[0],k.async=1,k.src=r,a.parentNode.insertBefore(k,a)
        })(window, document,'script','https://mc.yandex.ru/metrika/tag.js?id=111697118', 'ym');

        ym(111697118, 'init', {ssr:true, webvisor:true, clickmap:true, ecommerce:"dataLayer", referrer: document.referrer, url: location.href, accurateTrackBounce:true, trackLinks:true});
    </script>
    <noscript><div><img src="https://mc.yandex.ru/watch/111697118" style="position:absolute; left:-9999px;" alt="" /></div></noscript>
    <!-- /Yandex.Metrika counter -->"""


# ============================================================
# ИЗВЛЕЧЕНИЕ МЕТАДАННЫХ ИЗ .py ФАЙЛОВ
# ============================================================

def extract_ast_value(node: ast.AST) -> Any:
    """Рекурсивно извлекает значение из AST-ноды (литералы, списки, словари)."""
    if isinstance(node, ast.Constant):
        return node.value
    elif isinstance(node, ast.Name):
        if node.id == "True":
            return True
        elif node.id == "False":
            return False
        elif node.id == "None":
            return None
        return node.id
    elif isinstance(node, ast.List):
        return [extract_ast_value(elt) for elt in node.elts]
    elif isinstance(node, ast.Dict):
        result = {}
        for key, value in zip(node.keys, node.values):
            k = extract_ast_value(key) if key is not None else None
            v = extract_ast_value(value)
            result[k] = v
        return result
    elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -extract_ast_value(node.operand)
    elif isinstance(node, ast.Attribute):
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.append(current.id)
        return ".".join(reversed(parts))
    elif isinstance(node, ast.Call):
        func_name = extract_ast_value(node.func)
        args = [extract_ast_value(arg) for arg in node.args]
        return {"__call__": func_name, "__args__": args}
    else:
        return f"<unparsed:{type(node).__name__}>"


def parse_parser_file(filepath: str) -> List[Dict[str, Any]]:
    """Парсит .py файл и извлекает метаданные всех классов-парсеров."""
    with open(filepath, "r", encoding="utf-8") as f:
        source = f.read()

    try:
        tree = ast.parse(source, filename=filepath)
    except SyntaxError:
        print(f"  [ОШИБКА] Синтаксическая ошибка: {filepath}")
        return []

    parsers = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        inherits = False
        for base in node.bases:
            base_name = ""
            if isinstance(base, ast.Name):
                base_name = base.id
            elif isinstance(base, ast.Attribute):
                base_name = base.attr
            if "parser" in base_name.lower() or "base" in base_name.lower() or base_name == "ABC":
                inherits = True
                break

        if not inherits:
            continue

        parser_data = {
            "class_name": node.name,
            "file_name": os.path.basename(filepath).replace(".py", ""),
            "NAME": "",
            "DESCRIPTION": "",
            "PREMIUM": False,
            "PIC": None,
            "PATH": "",
            "COLUMNS": [],
        }

        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name) and target.id in (
                        "NAME", "DESCRIPTION", "PREMIUM", "PIC", "PATH", "COLUMNS"
                    ):
                        value = extract_ast_value(item.value)
                        parser_data[target.id] = value

        columns_raw = parser_data["COLUMNS"]
        if isinstance(columns_raw, list) and columns_raw:
            parser_data["COLUMNS"] = extract_columns_with_groups(source, node)
        else:
            parser_data["COLUMNS"] = []

        if not parser_data["NAME"]:
            continue

        parsers.append(parser_data)

    return parsers


def resolve_f_string(text: str) -> str:
    """Заменяет вызовы sym_on()/sym_off() в f-строках на отображаемые символы."""
    text = text.replace('{sym_on()}', '\u25a3')
    text = text.replace('{sym_off()}', '\u25a1')
    return text


def extract_columns_with_groups(source: str, class_node: ast.ClassDef) -> List[Dict[str, Any]]:
    """Извлекает столбцы с группировкой по комментариям."""
    lines = source.split("\n")
    columns_start = None
    columns_end = None
    class_start = class_node.lineno - 1

    for i in range(class_start, min(class_start + 200, len(lines))):
        if lines[i].strip().startswith("COLUMNS"):
            columns_start = i
            break

    if columns_start is None:
        return []

    bracket_depth = 0
    found_open = False
    for i in range(columns_start, min(columns_start + 500, len(lines))):
        for ch in lines[i]:
            if ch == "[":
                bracket_depth += 1
                found_open = True
            elif ch == "]":
                bracket_depth -= 1
                if found_open and bracket_depth == 0:
                    columns_end = i
                    break
        if columns_end is not None:
            break

    if columns_end is None:
        return []

    groups = []
    current_group_name = "Основные"
    current_group_items = []
    current_col_name = None

    i = columns_start
    while i <= columns_end:
        line = lines[i].strip()
        i += 1

        if line.startswith("#"):
            comment = line.lstrip("# ").strip()
            if comment and "tooltip" not in comment.lower() and "name" not in comment.lower():
                if comment and not comment.startswith("{") and not comment.startswith("'"):
                    if current_group_items:
                        groups.append({"group": current_group_name, "items": current_group_items})
                        current_group_items = []
                    current_group_name = comment

        name_match = re.search(r"['\"]name['\"]:\s*['\"](.+?)['\"]", line)
        if name_match:
            current_col_name = name_match.group(1)

        tooltip_text = None

        # 1. Многострочная обычная строка (тройные одинарные кавычки без f)
        if "'''" in line and "f'''" not in line:
            m = re.search(r"""['"]tooltip['"]:\s*'{3}""", line)
            if m:
                text_start = line.find("'''") + 3
                collected = line[text_start:]
                while i <= columns_end:
                    next_line = lines[i]
                    i += 1
                    if "'''" in next_line:
                        collected += "\n" + next_line[:next_line.find("'''")]
                        break
                    collected += "\n" + next_line
                tooltip_text = collected.strip()

        # 2. Многострочная f-строка (тройные одинарные кавычки)
        if tooltip_text is None and "f'''" in line:
            m = re.search(r"""['"]tooltip['"]:\s*f'{3}""", line)
            if m:
                text_start = line.find("f'''") + 4
                collected = line[text_start:]
                while i <= columns_end:
                    next_line = lines[i]
                    i += 1
                    if "'''" in next_line:
                        collected += "\n" + next_line[:next_line.find("'''")]
                        break
                    collected += "\n" + next_line
                tooltip_text = resolve_f_string(collected.strip())

        # 3. Многострочная f-строка (тройные двойные кавычки)
        if tooltip_text is None and 'f"""' in line:
            m = re.search(r"""['"]tooltip['"]:\s*f"{3}""", line)
            if m:
                text_start = line.find('f"""') + 4
                collected = line[text_start:]
                while i <= columns_end:
                    next_line = lines[i]
                    i += 1
                    if '"""' in next_line:
                        collected += "\n" + next_line[:next_line.find('"""')]
                        break
                    collected += "\n" + next_line
                tooltip_text = resolve_f_string(collected.strip())

        # 4. Однострочная обычная строка
        if tooltip_text is None:
            m = re.search(r"""['"]tooltip['"]:\s*(['"])(.*?)\1""", line)
            if m:
                tooltip_text = m.group(2)

        # 5. Однострочная f-строка — после тройных кавычек
        if tooltip_text is None:
            m = re.search(r"""['"]tooltip['"]:\s*f(['"])(.*?)\1""", line)
            if m:
                tooltip_text = resolve_f_string(m.group(2))

        if tooltip_text is not None and current_col_name:
            current_group_items.append({"name": current_col_name, "tooltip": tooltip_text})
            current_col_name = None

    if current_group_items:
        groups.append({"group": current_group_name, "items": current_group_items})

    return groups


# ============================================================
# УТИЛИТЫ
# ============================================================

def parse_name(full_name: str) -> Dict[str, str]:
    """Разбивает NAME на техническую и официальную части."""
    match = re.match(r'^(\S+)\s+(.+)$', full_name)
    if match:
        return {"code": match.group(1), "title": match.group(2).strip()}
    return {"code": "", "title": full_name}


def format_path_display(path: str) -> str:
    """Форматирует PATH для каталога: '01. ЛС/4. Другие/' → 'ЛС → Другие'."""
    if not path:
        return "Без группы"
    path = path.rstrip("/")
    match = re.match(r'^\S+\s+(.+)$', path)
    if match:
        path = match.group(1)
    path = re.sub(r'/\d+\.\s*', ' → ', path)
    return path


def make_slug(filename: str) -> str:
    """Создаёт slug из имени файла (без .py)."""
    return filename.replace(".py", "")


def escape_html(text: str) -> str:
    """Экранирует HTML-спецсимволы."""
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def path_sort_key(path: str) -> tuple:
    """Ключ сортировки для PATH — по числовому префиксу."""
    match = re.match(r'(\d+)', path)
    if match:
        return (int(match.group(1)), path)
    return (999, path)


def load_template(path: str) -> str:
    """Загружает HTML-шаблон из файла."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# ============================================================
# ГЕНЕРАЦИЯ HTML-ФРАГМЕНТОВ
# ============================================================

def build_pic_html(pic: str, full_name: str) -> str:
    """Генерирует HTML-фрагмент со скриншотом."""
    if pic:
        return f'''            <!-- Скриншот -->
            <div class="mb-4">
                <h5 class="mb-3"><i class="bi bi-image text-primary"></i> Скриншот</h5>
                <div class="text-center">
                    <img src="pic/{pic}" alt="{escape_html(full_name)}" class="img-fluid shadow-sm" style="max-height: 600px;">
                </div>
            </div>'''
    return '''            <!-- Скриншот (заглушка) -->
            <div class="mb-4">
                <h5 class="mb-3"><i class="bi bi-image text-primary"></i> Скриншот</h5>
                <div class="text-center p-5 bg-light rounded">
                    <i class="bi bi-image display-1 text-muted"></i>
                    <p class="text-muted mt-2">Скриншот пока не добавлен</p>
                </div>
            </div>'''


def format_tooltip(text: str) -> str:
    """Форматирует tooltip: переносы строк → <br>, убирает лишние отступы."""
    if not text:
        return ""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if stripped:
            cleaned.append(stripped)
    return "<br>".join(cleaned)


def build_columns_html(columns: list) -> str:
    """Генерирует HTML-фрагмент с таблицей столбцов."""
    if not columns:
        return ""

    table_rows = ""
    total = 0
    for group in columns:
        group_name = group.get("group", "")
        items = group.get("items", [])
        total += len(items)

        for item in items:
            tooltip = format_tooltip(item.get("tooltip", ""))
            table_rows += f'''
                            <tr>
                                <td class="fw-bold col-name">{escape_html(item.get("name", ""))}</td>
                                <td class="col-desc">{tooltip}</td>
                            </tr>'''

    return f'''
            <!-- Таблица столбцов -->
            <div class="mb-4">
                <h5 class="mb-3"><i class="bi bi-table text-primary"></i> Столбцы парсера</h5>
                <div class="table-responsive">
                    <table class="table table-bordered mb-0">
                        <thead class="table-primary">
                            <tr>
                                <th class="col-name">Столбец</th>
                                <th class="col-desc">Описание</th>
                            </tr>
                        </thead>
                        <tbody>{table_rows}
                        </tbody>
                    </table>
                </div>
                <p class="text-muted small mt-2 mb-0">
                    <i class="bi bi-info-circle"></i> Всего столбцов: {total}
                </p>
            </div>'''


# ============================================================
# ГЕНЕРАЦИЯ СТРАНИЦ
# ============================================================

def generate_parser_page(parser: Dict[str, Any], template: str) -> str:
    """Генерирует HTML-страницу для одного парсера из шаблона."""
    full_name = parser["NAME"]
    name_parts = parse_name(full_name)
    description = parser.get("DESCRIPTION", "")
    premium = parser.get("PREMIUM", False)
    pic = parser.get("PIC")
    path = parser.get("PATH", "")
    columns = parser.get("COLUMNS", [])

    short_name = name_parts["title"] if name_parts["title"] else full_name
    title_text = f"{short_name} - Анализ смет"
    meta_desc_plain = re.sub(r'<[^>]+>', '', description) if description else ""
    meta_desc = meta_desc_plain[:160] if meta_desc_plain else f"Описание парсера {full_name}"
    premium_badge = ' <i class="bi bi-star-fill text-warning"></i>' if premium else ""

    # Полный путь: PATH + "/" + NAME
    if path:
        path_display = path.rstrip("/") + "/" + full_name
    else:
        path_display = full_name

    # Подставляем переменные в шаблон
    html = template
    html = html.replace("{{TITLE}}", escape_html(title_text))
    html = html.replace("{{META_DESC}}", escape_html(meta_desc))
    html = html.replace("{{FULL_NAME}}", escape_html(short_name))
    html = html.replace("{{PREMIUM_BADGE}}", premium_badge)
    html = html.replace("{{PATH_DISPLAY}}", escape_html(path_display))
    html = html.replace("{{DESCRIPTION}}", description if description else "")
    html = html.replace("{{PIC_HTML}}", build_pic_html(pic, full_name))
    html = html.replace("{{COLUMNS_HTML}}", build_columns_html(columns))

    return html


def generate_catalog_page(parsers: List[Dict[str, Any]]) -> str:
    """Генерирует страницу-каталог всех парсеров, сгруппированных по PATH (аккордеон + пилюли)."""
    groups = OrderedDict()
    for p in parsers:
        path = p.get("PATH", "Без группы")
        if path not in groups:
            groups[path] = []
        groups[path].append(p)

    sorted_groups = OrderedDict(sorted(groups.items(), key=lambda x: path_sort_key(x[0])))

    # Генерация аккордеона
    accordion_html = ""
    for idx, (path, group_parsers) in enumerate(sorted_groups.items()):
        path_display = escape_html(format_path_display(path)) if path else "Без группы"

        items_html = ""
        for p in group_parsers:
            slug = make_slug(p["file_name"])
            full_name = p["NAME"]
            parser_display = escape_html(parse_name(full_name)["title"])
            columns_count = sum(len(g.get("items", [])) for g in p.get("COLUMNS", []))
            if columns_count == 0:
                columns_count = len(p.get("COLUMNS", []))

            items_html += f'''
                        <a href="parsers/{slug}.html" class="text-decoration-none">
                            <div class="parser-item" data-name="{escape_html(full_name)}">
                                <span class="icon blue"><i class="bi bi-table"></i></span>
                                <span class="parser-name">{parser_display}</span>
                                <span class="parser-badge ms-auto">{columns_count} столбцов</span>
                            </div>
                        </a>'''

        accordion_html += f'''
                <div class="accordion-item">
                    <h2 class="accordion-header">
                        <button class="accordion-button collapsed" type="button" data-bs-toggle="collapse" data-bs-target="#collapse{idx}">
                            <i class="bi bi-folder me-2 text-primary"></i>
                            {path_display}
                            <span class="category-count">({len(group_parsers)})</span>
                        </button>
                    </h2>
                    <div id="collapse{idx}" class="accordion-collapse collapse" data-bs-parent="#parserAccordion">
                        <div class="accordion-body p-0">{items_html}
                        </div>
                    </div>
                </div>'''

    total_count = len(parsers)
    premium_count = sum(1 for p in parsers if p.get("PREMIUM", False))

    return f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    {YANDEX_METRIKA}
    <link rel="icon" type="image/png" href="icon.png">
    <link rel="icon" type="image/x-icon" href="icon.ico">
    <title>Парсеры - Анализ смет</title>
    <meta name="description" content="Каталог парсеров приложения Анализ смет. Все доступные парсеры для анализа файлов ГРАНД-Смета (.gsfx).">

    <!-- Bootstrap 5 CSS -->
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
    <!-- Bootstrap Icons -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">

    <style>
        body {{
            background-color: #f8f9fa;
        }}
        .page-header {{
            background: linear-gradient(135deg, #0d6efd 0%, #0a58ca 100%);
            color: white;
            padding: 60px 0 40px;
        }}
        .footer {{
            background-color: #212529;
            color: #adb5bd;
        }}
        .navbar-brand {{
            font-size: 1.3rem !important;
            letter-spacing: 1.5px;
        }}
        .search-box {{
            max-width: 500px;
            margin: 0 auto 30px;
        }}
        .accordion-button:not(.collapsed) {{
            background-color: #e3f0ff;
            color: #0d6efd;
            font-weight: 600;
        }}
        .accordion-button:focus {{
            box-shadow: none;
            border-color: #0d6efd;
        }}
        .accordion-item {{
            border: 1px solid #dee2e6;
            margin-bottom: 8px;
            border-radius: 10px !important;
            overflow: hidden;
        }}
        .parser-badge {{
            font-size: 0.65rem;
            background: #f1f3f5;
            color: #6c757d;
            padding: 2px 10px;
            border-radius: 12px;
            white-space: nowrap;
        }}
        .parser-item {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 8px 16px;
            border-bottom: 1px solid #f1f3f5;
            transition: background-color 0.15s;
        }}
        .parser-item:hover {{
            background-color: #f8f9fa;
        }}
        .parser-item:last-child {{
            border-bottom: none;
        }}
        .parser-item .icon {{
            width: 32px;
            height: 32px;
            border-radius: 8px;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            font-size: 0.9rem;
        }}
        .parser-item .icon.blue {{ background: #e3f0ff; color: #0d6efd; }}
        .parser-item .icon.green {{ background: #e6f7ed; color: #198754; }}
        .parser-item .icon.orange {{ background: #fff3e0; color: #fd7e14; }}
        .parser-item .icon.purple {{ background: #f0e6ff; color: #6f42c1; }}
        .parser-item .icon.red {{ background: #fde8e8; color: #dc3545; }}
        .parser-item .icon.teal {{ background: #e0f7f7; color: #20c997; }}
        .parser-item .icon.pink {{ background: #fce4ec; color: #d63384; }}
        .parser-item .icon.indigo {{ background: #e8e6ff; color: #6610f2; }}
        .category-count {{
            font-size: 0.8rem;
            color: #6c757d;
            margin-left: 8px;
        }}
        .parser-name {{
            color: #212529;
            font-size: 0.9rem;
        }}
    </style>
</head>
<body>

    <!-- НАВИГАЦИЯ -->
    <nav class="navbar navbar-dark bg-dark sticky-top navbar-expand-lg">
        <div class="container">
            <a class="navbar-brand fw-bold text-uppercase" href="index.html">
                <i class="bi bi-bar-chart-fill"></i> Анализ смет
            </a>
            <button class="navbar-toggler" type="button" data-bs-toggle="offcanvas" data-bs-target="#offcanvasMenu">
                <span class="navbar-toggler-icon"></span>
            </button>

            <div class="offcanvas offcanvas-end offcanvas-lg bg-dark" tabindex="-1" id="offcanvasMenu">
                <div class="offcanvas-header d-lg-none">
                    <h5 class="offcanvas-title text-white text-uppercase">Меню</h5>
                    <button type="button" class="btn-close btn-close-white" data-bs-dismiss="offcanvas" data-bs-target="#offcanvasMenu"></button>
                </div>
                <div class="offcanvas-body">
                    <ul class="navbar-nav justify-content-end flex-grow-1 pe-3">
                        <li class="nav-item">
                            <a class="nav-link" href="index.html">Главная</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link active" href="parsers.html">Парсеры</a>
                        </li>
                        <li class="nav-item">
                            <a class="nav-link" href="videos.html">Помощь</a>
                        </li>
                        <li class="nav-item mt-2 mt-lg-0 ms-lg-3">
                            <a class="btn btn-warning fw-bold w-100 w-lg-auto" href="rate.html">
                                Тарифы
                            </a>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    </nav>

    <!-- ЗАГОЛОВОК -->
    <section class="page-header text-center">
        <div class="container">
            <h1 class="display-5 fw-bold mb-3">Парсеры</h1>
            <p class="lead mb-3">Полный каталог парсеров для анализа файлов ГРАНД-Смета</p>

            <!-- Поиск -->
            <div class="search-box">
                <div class="input-group position-relative rounded">
                    <span class="input-group-text bg-white border-0 rounded-start">
                        <i class="bi bi-search text-muted"></i>
                    </span>
                    <input type="text" class="form-control border-0 rounded-end pe-5" id="parserSearch" placeholder="Найти парсер...">
                    <button class="btn position-absolute top-50 end-0 translate-middle-y me-2 p-0 border-0 bg-transparent d-none" id="clearSearch" type="button" style="z-index: 5;">
                        <i class="bi bi-x-lg text-muted"></i>
                    </button>
                </div>
            </div>

            <!-- Статистика -->
            <div class="text-white-50 small">
                <i class="bi bi-puzzle"></i> Всего парсеров: <span id="parserCount">{total_count}</span>
                <span class="ms-3"><i class="bi bi-star-fill text-warning"></i> Частные: {premium_count}</span>
            </div>
        </div>
    </section>

    <!-- КОНТЕНТ -->
    <section class="py-5">
        <div class="container" style="max-width: 850px;">

            <!-- АККОРДЕОН -->
            <div class="accordion" id="parserAccordion">
{accordion_html}
            </div>

            <!-- Кнопки -->
            <div class="mt-4 d-flex flex-wrap gap-2 justify-content-center">
                <button class="btn btn-outline-primary btn-lg" onclick="collapseAll()">
                    <i class="bi bi-arrows-collapse"></i> Свернуть все
                </button>
                <button class="btn btn-outline-secondary btn-lg" onclick="expandAll()">
                    <i class="bi bi-arrows-expand"></i> Развернуть все
                </button>
            </div>

            <!-- Подсказка -->
            <div class="text-center mt-3">
                <span class="text-muted small">
                    <i class="bi bi-info-circle"></i> Нажмите на категорию, чтобы увидеть список парсеров
                </span>
            </div>

        </div>
    </section>

    <!-- ПОДВАЛ -->
    <footer class="footer py-4 text-center">
        <div class="container">
            <p class="mb-2">
                <a href="index.html" class="text-white-50 text-decoration-none">
                    <i class="bi bi-arrow-left"></i> На главную
                </a>
            </p>
            <p class="mb-2 small text-white-50">
                Используя сайт, вы принимаете
                <a href="legal/privacy.html" class="text-white-50 text-decoration-none">Политику конфиденциальности</a>
                и
                <a href="legal/cookie.html" class="text-white-50 text-decoration-none">Cookie-политику</a>.
            </p>
            <p class="mb-0 small">&copy; 2026 Анализ смет. Все права защищены.</p>
        </div>
    </footer>

    <!-- Bootstrap 5 JS -->
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>

    <!-- Скрипт -->
    <script>
        var searchInput = document.getElementById('parserSearch');
        var clearBtn = document.getElementById('clearSearch');

        function doSearch() {{
            var term = searchInput.value.toLowerCase();
            // Показывать/скрывать крестик
            clearBtn.classList.toggle('d-none', searchInput.value === '');
            // Фильтрация
            document.querySelectorAll('.parser-item').forEach(function(item) {{
                var name = (item.getAttribute('data-name') || '').toLowerCase();
                var text = item.textContent.toLowerCase();
                var match = name.includes(term) || text.includes(term);
                item.closest('a').style.display = match ? '' : 'none';
            }});
            // Скрывать пустые группы
            document.querySelectorAll('.accordion-item').forEach(function(group) {{
                var anyVisible = false;
                group.querySelectorAll('.parser-item').forEach(function(item) {{
                    if (item.closest('a').style.display !== 'none') anyVisible = true;
                }});
                group.style.display = anyVisible ? '' : 'none';
            }});
            // Обновлять счётчик
            var visibleCount = 0;
            document.querySelectorAll('.parser-item').forEach(function(item) {{
                if (item.closest('a').style.display !== 'none') visibleCount++;
            }});
            document.getElementById('parserCount').textContent = visibleCount;
        }}

        searchInput.addEventListener('input', doSearch);

        clearBtn.addEventListener('click', function() {{
            searchInput.value = '';
            doSearch();
            searchInput.focus();
        }});

        // Развернуть все
        function expandAll() {{
            document.querySelectorAll('.accordion-collapse').forEach(function(el) {{
                var bsCollapse = new bootstrap.Collapse(el, {{ toggle: false }});
                bsCollapse.show();
            }});
            document.querySelectorAll('.accordion-button').forEach(function(btn) {{
                btn.classList.remove('collapsed');
                btn.setAttribute('aria-expanded', 'true');
            }});
        }}

        // Свернуть все
        function collapseAll() {{
            document.querySelectorAll('.accordion-collapse').forEach(function(el) {{
                var bsCollapse = new bootstrap.Collapse(el, {{ toggle: false }});
                bsCollapse.hide();
            }});
            document.querySelectorAll('.accordion-button').forEach(function(btn) {{
                btn.classList.add('collapsed');
                btn.setAttribute('aria-expanded', 'false');
            }});
        }}
    </script>
</body>
</html>'''


# ============================================================
# ОБНОВЛЕНИЕ SITEMAP
# ============================================================

def update_sitemap(parsers: List[Dict[str, Any]]) -> None:
    """Обновляет sitemap.xml."""
    sitemap_path = os.path.join(SITE_DIR, "sitemap.xml")

    base_urls = [
        ("index.html", "1.0"),
        ("videos.html", "0.8"),
        ("pay.html", "0.7"),
        ("rate.html", "0.9"),
        ("parsers.html", "0.8"),
    ]

    today = date.today().isoformat()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for url, priority in base_urls:
        lines.extend([
            "  <url>",
            f"    <loc>{DOMAIN}/{url}</loc>",
            f"    <lastmod>{today}</lastmod>",
            "    <changefreq>monthly</changefreq>",
            f"    <priority>{priority}</priority>",
            "  </url>",
        ])

    for p in parsers:
        slug = make_slug(p["file_name"])
        lines.extend([
            "  <url>",
            f"    <loc>{DOMAIN}/parsers/{slug}.html</loc>",
            f"    <lastmod>{today}</lastmod>",
            "    <changefreq>monthly</changefreq>",
            "    <priority>0.6</priority>",
            "  </url>",
        ])

    lines.append("</urlset>")

    with open(sitemap_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"  [OK] sitemap.xml ({len(base_urls) + len(parsers)} URL)")


# ============================================================
# КОПИРОВАНИЕ СКРИНШОТОВ
# ============================================================

def copy_screenshots() -> None:
    """Копирует скриншоты в parsers/pic/."""
    dest_dir = os.path.join(PARSERS_OUTPUT_DIR, "pic")
    os.makedirs(dest_dir, exist_ok=True)

    if not os.path.isdir(PIC_DIR):
        print(f"  [ПРЕДУПРЕЖДЕНИЕ] Папка скриншотов не найдена: {PIC_DIR}")
        return

    count = 0
    for filename in os.listdir(PIC_DIR):
        if filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            shutil.copy2(os.path.join(PIC_DIR, filename), os.path.join(dest_dir, filename))
            count += 1

    print(f"  [OK] Скопировано {count} скриншотов в parsers/pic/")


# ============================================================
# ОСНОВНАЯ ФУНКЦИЯ
# ============================================================

def main():
    print("=" * 60)
    print("  ГЕНЕРАТОР СТРАНИЦ ПАРСЕРОВ")
    print("  Сайт: analizsmet.ru")
    print("=" * 60)

    # Загружаем шаблон
    print(f"\n[0/5] Загрузка шаблона: {os.path.basename(TEMPLATE_PARSER)}")
    template = load_template(TEMPLATE_PARSER)
    print(f"  [OK] Шаблон загружен ({len(template)} байт)")

    # 1. Сканируем .py файлы
    print(f"\n[1/5] Сканирование парсеров: {PARSERS_DIR}")
    all_parsers = []
    py_files = sorted(f for f in os.listdir(PARSERS_DIR) if f.endswith(".py") and f not in SKIP_FILES)

    for filename in py_files:
        parsers = parse_parser_file(os.path.join(PARSERS_DIR, filename))
        all_parsers.extend(parsers)

    print(f"  [OK] Найдено {len(all_parsers)} парсеров в {len(py_files)} файлах")

    if not all_parsers:
        print("  [ОШИБКА] Парсеры не найдены.")
        return

    # 2. Сохраняем JSON
    print(f"\n[2/5] Сохранение parsers.json")
    json_path = os.path.join(SITE_DIR, "parsers.json")
    json_data = [{
        "file_name": p["file_name"],
        "class_name": p["class_name"],
        "NAME": p["NAME"],
        "DESCRIPTION": p.get("DESCRIPTION", ""),
        "PREMIUM": p.get("PREMIUM", False),
        "PIC": p.get("PIC"),
        "PATH": p.get("PATH", ""),
        "COLUMNS": p.get("COLUMNS", []),
    } for p in all_parsers]

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    print(f"  [OK] parsers.json ({len(json_data)} записей)")

    # 3. Копируем скриншоты
    print(f"\n[3/5] Копирование скриншотов")
    copy_screenshots()

    # 4. Генерируем HTML-страницы
    print(f"\n[4/5] Генерация HTML-страниц")
    os.makedirs(PARSERS_OUTPUT_DIR, exist_ok=True)
    for p in all_parsers:
        slug = make_slug(p["file_name"])
        html = generate_parser_page(p, template)
        with open(os.path.join(PARSERS_OUTPUT_DIR, f"{slug}.html"), "w", encoding="utf-8") as f:
            f.write(html)
    print(f"  [OK] Сгенерировано {len(all_parsers)} страниц в parsers/")

    # Убираем старые файлы из корня
    keep_files = {"index.html", "videos.html", "rate.html", "pay.html", "404.html", "error.html",
                  "parsers.html", "yandex_3b77755ac8d47a10.html", "generate_parsers.py",
                  "parsers.json", "AGENTS.md", "README.md", "CNAME", "sitemap.xml"}
    removed = 0
    for f in os.listdir(SITE_DIR):
        full = os.path.join(SITE_DIR, f)
        if os.path.isfile(full) and f.endswith(".html") and f not in keep_files:
            os.remove(full)
            removed += 1
    if removed:
        print(f"  [OK] Удалено {removed} старых файлов из корня")

    # 5. Генерируем каталог
    print(f"\n[5/5] Генерация каталога parsers.html")
    with open(os.path.join(SITE_DIR, "parsers.html"), "w", encoding="utf-8") as f:
        f.write(generate_catalog_page(all_parsers))
    print(f"  [OK] parsers.html")

    # sitemap
    update_sitemap(all_parsers)

    print("\n" + "=" * 60)
    print("  ГОТОВО!")
    print(f"  Парсеров: {len(all_parsers)}")
    print(f"  Страниц:  {len(all_parsers)} + parsers.html")
    print("=" * 60)


if __name__ == "__main__":
    main()
