from __future__ import annotations

import json
import math
import os
import base64
import binascii
import ast
import operator
import unicodedata
import re
import csv
import html
import io
import sqlite3
import uuid
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "masterficha.sqlite3"
MAX_BODY = 4_000_000
MAX_IMAGE_BYTES = 2_000_000


def connect_db() -> sqlite3.Connection:
    DATA_DIR.mkdir(exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialize_db() -> None:
    with connect_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS rpgs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fichas (
                id TEXT PRIMARY KEY,
                rpg_id TEXT NOT NULL REFERENCES rpgs(id) ON DELETE RESTRICT,
                name TEXT NOT NULL,
                history TEXT NOT NULL DEFAULT '',
                attributes TEXT NOT NULL DEFAULT '[]',
                powers TEXT NOT NULL DEFAULT '[]',
                inventory TEXT NOT NULL DEFAULT '[]',
                resource_materials TEXT NOT NULL DEFAULT '{"fields":[],"rows":[]}',
                tags TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS fichas_rpg_idx ON fichas(rpg_id);
            CREATE TABLE IF NOT EXISTS ficha_registros (
                id TEXT PRIMARY KEY,
                ficha_id TEXT NOT NULL REFERENCES fichas(id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('treino', 'missao', 'evento')),
                occurred_on TEXT NOT NULL,
                description TEXT NOT NULL,
                image_data TEXT NOT NULL,
                gains TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS registros_ficha_date_idx ON ficha_registros(ficha_id, occurred_on DESC);
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(fichas)")}
        if "resource_materials" not in columns:
            db.execute("ALTER TABLE fichas ADD COLUMN resource_materials TEXT NOT NULL DEFAULT '{\"fields\":[],\"rows\":[]}'")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clean_text(value: object, field: str, limit: int, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"O campo {field} deve ser texto.")
    value = value.strip()
    if required and not value:
        raise ValueError(f"Preencha o campo {field}.")
    if len(value) > limit:
        raise ValueError(f"O campo {field} deve ter no máximo {limit} caracteres.")
    return value


def clean_rows(value: object, field: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError(f"A lista {field} é inválida (limite de 100 itens).")
    rows = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError(f"Há um item inválido em {field}.")
        if field == "attributes":
            name = clean_text(row.get("name", ""), "nome do atributo", 80, True)
            value_text = clean_text(row.get("value", ""), "valor do atributo", 120)
            rows.append({"name": name, "value": value_text})
        elif field == "powers":
            name = clean_text(row.get("name", ""), "nome do poder", 100, True)
            description = clean_text(row.get("description", ""), "descrição do poder", 1000)
            effects = row.get("effects", [])
            if not isinstance(effects, list) or len(effects) > 20:
                raise ValueError("Informe até 20 modificadores para cada poder.")
            clean_effects = []
            for effect in effects:
                if not isinstance(effect, dict):
                    raise ValueError("Há um modificador de atributo inválido.")
                attribute = clean_text(effect.get("attribute", ""), "atributo modificado", 80, True)
                operation = effect.get("operation")
                if operation not in ("add", "subtract", "multiply", "divide"):
                    raise ValueError("Escolha somar, subtrair, multiplicar ou dividir.")
                amount = effect.get("amount")
                if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0 or amount > 1_000_000 or not math.isfinite(amount):
                    raise ValueError("O valor do modificador deve ser maior que zero.")
                clean_effects.append({"attribute": attribute, "operation": operation, "amount": amount})
            rows.append({"name": name, "description": description, "effects": clean_effects})
        else:
            name = clean_text(row.get("name", ""), "nome do item", 100, True)
            quantity = clean_text(row.get("quantity", ""), "quantidade", 40)
            description = clean_text(row.get("description", ""), "descrição do item", 500)
            rows.append({"name": name, "quantity": quantity, "description": description})
    return rows


def validate_attribute_formulas(attributes: list[dict[str, str]]) -> None:
    """Validate arithmetic expressions and resolve parenthesized attribute references."""
    by_name = {row["name"].casefold(): row for row in attributes}
    if len(by_name) != len(attributes):
        raise ValueError("Os nomes dos atributos devem ser únicos.")
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
                  ast.Div: operator.truediv, ast.Pow: operator.pow, ast.USub: operator.neg,
                  ast.UAdd: operator.pos}
    resolved: dict[str, float] = {}
    visiting: set[str] = set()

    def evaluate(name: str) -> float:
        key = name.casefold()
        if key in resolved:
            return resolved[key]
        if key in visiting:
            raise ValueError("As fórmulas dos atributos não podem formar dependências circulares.")
        visiting.add(key)
        expression = re.sub(r"^\\?=", "", by_name[key]["value"].strip()).replace(",", ".")
        # A parenthesized word/name is an attribute reference. Parenthesized math remains math.
        expression = re.sub(r"\(([\wÀ-ÿ][\wÀ-ÿ ]*)\)", lambda match: str(evaluate(match.group(1).strip()))
                            if match.group(1).strip().casefold() in by_name else match.group(0), expression)
        expression = re.sub(r"\b(SE|E|OU|NAO)\s*\(", lambda m: m.group(1).upper() + "(", expression, flags=re.IGNORECASE)
        expression = expression.replace(";", ",").replace("<>", "!=")
        expression = re.sub(r"(?<![<>=!])=(?!=)", "==", expression)
        expression = expression.replace("^", "**")
        try:
            tree = ast.parse(expression, mode="eval")
            def visit(node: ast.AST) -> float:
                if isinstance(node, ast.Expression): return visit(node.body)
                if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool): return float(node.value)
                if isinstance(node, ast.BinOp) and type(node.op) in operations:
                    left, right = visit(node.left), visit(node.right)
                    if isinstance(node.op, ast.Pow) and abs(right) > 100: raise ValueError("Expoente de fórmula muito grande.")
                    return operations[type(node.op)](left, right)
                if isinstance(node, ast.UnaryOp) and type(node.op) in operations: return operations[type(node.op)](visit(node.operand))
                if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not): return not bool(visit(node.operand))
                if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
                    values = [bool(visit(value)) for value in node.values]
                    return all(values) if isinstance(node.op, ast.And) else any(values)
                if isinstance(node, ast.Compare) and len(node.ops) == 1:
                    left, right = visit(node.left), visit(node.comparators[0])
                    comparisons = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
                                   ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}
                    if type(node.ops[0]) in comparisons: return comparisons[type(node.ops[0])](left, right)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    function = "".join(char for char in unicodedata.normalize("NFD", node.func.id.upper()) if unicodedata.category(char) != "Mn")
                    if node.keywords:
                        raise ValueError("As funções aceitam apenas argumentos separados por ponto e vírgula.")
                    if function == "SE" and len(node.args) == 3:
                        return visit(node.args[1] if bool(visit(node.args[0])) else node.args[2])
                    if function == "E" and node.args: return all(bool(visit(arg)) for arg in node.args)
                    if function == "OU" and node.args: return any(bool(visit(arg)) for arg in node.args)
                    if function == "NAO" and len(node.args) == 1: return not bool(visit(node.args[0]))
                    args = [float(visit(arg)) for arg in node.args]
                    if function == "MINIMO" and args: return min(args)
                    if function == "MAXIMO" and args: return max(args)
                    if function == "SOMA" and args: return sum(args)
                    if function == "MEDIA" and args: return sum(args) / len(args)
                    if function == "INT" and len(args) == 1: return math.floor(args[0])
                    if function == "TRUNCAR" and len(args) in (1, 2):
                        digits = int(args[1]) if len(args) == 2 else 0
                        if abs(digits) > 100: raise ValueError("Casas decimais de TRUNCAR muito grandes.")
                        scale = 10 ** digits
                        return math.trunc(args[0] * scale) / scale
                    if function == "RAIZ" and len(args) == 1: return math.sqrt(args[0])
                    if function == "ABS" and len(args) == 1: return abs(args[0])
                    if function == "ARRED" and len(args) in (1, 2):
                        digits = int(args[1]) if len(args) == 2 else 0
                        if abs(digits) > 100: raise ValueError("Casas decimais de ARRED muito grandes.")
                        scale = 10 ** digits
                        return math.copysign(math.floor(abs(args[0]) * scale + 0.5) / scale, args[0])
                    if function == "POTENCIA" and len(args) == 2: return args[0] ** args[1]
                    if function == "MOD" and len(args) == 2:
                        if args[1] == 0: raise ZeroDivisionError()
                        return args[0] - math.floor(args[0] / args[1]) * args[1]
                raise ValueError("Use números, referências entre parênteses, operações aritméticas, comparações e SE, E, OU ou NAO.")
            result = visit(tree)
            if not isinstance(result, (int, float)) or not math.isfinite(result) or abs(result) > 1e100: raise ValueError("O resultado da fórmula é inválido ou muito grande.")
        except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
            raise ValueError(f"Fórmula inválida no atributo {name}.") from exc
        visiting.remove(key)
        resolved[key] = float(result)
        return float(result)

    for attribute in attributes:
        evaluate(attribute["name"])


def clean_tags(value: object) -> list[str]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Informe até 20 tags.")
    tags = []
    for item in value:
        tag = clean_text(item, "tag", 30)
        if tag and tag.casefold() not in {t.casefold() for t in tags}:
            tags.append(tag)
    return tags


def clean_resource_materials(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("A tabela de materiais de recursos é inválida.")
    fields = value.get("fields", [])
    rows = value.get("rows", [])
    if not isinstance(fields, list) or len(fields) > 30:
        raise ValueError("A tabela pode ter no máximo 30 campos.")
    if not isinstance(rows, list) or len(rows) > 200:
        raise ValueError("A tabela pode ter no máximo 200 linhas.")
    clean_fields = []
    field_ids = set()
    field_names = set()
    for field in fields:
        if not isinstance(field, dict):
            raise ValueError("Há um campo inválido na tabela de materiais.")
        field_id = clean_text(field.get("id", ""), "identificador do campo", 36, True)
        try:
            uuid.UUID(field_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("Um campo da tabela possui identificador inválido.") from exc
        name = clean_text(field.get("name", ""), "nome do campo", 60, True)
        folded_name = name.casefold()
        if field_id in field_ids or folded_name in field_names:
            raise ValueError("Os nomes e identificadores dos campos devem ser únicos.")
        field_ids.add(field_id)
        field_names.add(folded_name)
        clean_fields.append({"id": field_id, "name": name})
    clean_rows = []
    row_ids = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Há uma linha inválida na tabela de materiais.")
        row_id = clean_text(row.get("id", ""), "identificador da linha", 36, True)
        try:
            uuid.UUID(row_id)
        except (ValueError, AttributeError) as exc:
            raise ValueError("Uma linha da tabela possui identificador inválido.") from exc
        if row_id in row_ids:
            raise ValueError("Os identificadores das linhas devem ser únicos.")
        row_ids.add(row_id)
        values = row.get("values", {})
        if not isinstance(values, dict):
            raise ValueError("Os valores de uma linha da tabela são inválidos.")
        unknown = set(values) - field_ids
        if unknown:
            raise ValueError("Uma linha contém valores para campos removidos.")
        clean_values = {field["id"]: clean_text(values.get(field["id"], ""), "valor do material", 500) for field in clean_fields}
        clean_rows.append({"id": row_id, "values": clean_values})
    return {"fields": clean_fields, "rows": clean_rows}


def ficha_payload(row: sqlite3.Row) -> dict:
    result = dict(row)
    for field in ("attributes", "powers", "inventory", "tags"):
        result[field] = json.loads(result[field])
    result["resource_materials"] = json.loads(result.get("resource_materials") or '{"fields":[],"rows":[]}')
    return result


def build_record_export(db: sqlite3.Connection, ficha_id: str) -> bytes | None:
    ficha = db.execute("SELECT f.id, f.name, r.name AS rpg_name FROM fichas f JOIN rpgs r ON r.id=f.rpg_id WHERE f.id=?", (ficha_id,)).fetchone()
    if ficha is None:
        return None
    records = db.execute("SELECT * FROM ficha_registros WHERE ficha_id=? ORDER BY occurred_on, created_at", (ficha_id,)).fetchall()
    if not records:
        raise ValueError("Esta ficha ainda não possui registros para exportar.")
    type_names = {"treino": "Treino", "missao": "Missão", "evento": "Evento"}
    entries = []
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer, lineterminator="\r\n")
    writer.writerow(["RPG", "Personagem", "ID da ficha", "Tipo", "Data", "Descrição", "Ganhos de atributos", "Arquivo de imagem"])
    def safe_csv_cell(value: str) -> str:
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
    for row in records:
        item = dict(row)
        image_match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})", item["image_data"])
        if not image_match:
            raise ValueError("Um registro contém uma imagem inválida e não pode ser exportado.")
        mime = image_match.group(1)
        extension = {"png": "png", "jpeg": "jpg", "webp": "webp"}[mime]
        file_name = f"imagens/{item['kind']}_{item['occurred_on']}_{item['id'][:8]}.{extension}"
        image_bytes = base64.b64decode(image_match.group(2), validate=True)
        gains = json.loads(item["gains"])
        gains_text = "; ".join(f"{gain['attribute']} +{gain['amount']}" for gain in gains)
        entries.append({**item, "type_name": type_names[item["kind"]], "file_name": file_name, "image_bytes": image_bytes, "gains_text": gains_text})
        writer.writerow([safe_csv_cell(str(value)) for value in (ficha["rpg_name"], ficha["name"], ficha["id"], type_names[item["kind"]], item["occurred_on"], item["description"], gains_text, file_name)])
    escape = html.escape
    cards = []
    for item in entries:
        gains_html = f"<p class='gains'><strong>Ganhos:</strong> {escape(item['gains_text'])}</p>" if item["gains_text"] else ""
        cards.append(
            f"<article class='record'><div class='record-meta'><span>{escape(item['type_name'])}</span><time>{escape(item['occurred_on'])}</time></div>"
            f"<img src='{escape(item['file_name'])}' alt='Imagem de prova do registro de {escape(item['type_name'])}'>"
            f"<p>{escape(item['description'])}</p>{gains_html}</article>"
        )
    report = f"""<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Registros — {escape(ficha['name'])}</title>
<style>body{{font:16px/1.5 system-ui,Segoe UI,Arial,sans-serif;color:#202720;background:#f4f5f0;margin:0}}main{{max-width:900px;margin:36px auto;padding:0 20px}}header{{border-bottom:2px solid #657847;padding-bottom:18px;margin-bottom:24px}}h1{{margin:0 0 5px;font-size:30px}}.meta,.record-meta{{color:#5d685a}}.record{{background:white;border:1px solid #d6dbd0;border-radius:8px;padding:20px;margin:16px 0;break-inside:avoid}}.record-meta{{display:flex;justify-content:space-between;font-size:13px;text-transform:uppercase;letter-spacing:.06em}}img{{display:block;max-width:100%;max-height:560px;object-fit:contain;margin:16px auto 12px}}.record p{{white-space:pre-wrap}}.gains{{padding-top:10px;border-top:1px solid #e2e5df;font-size:14px}}footer{{margin:30px 0;color:#657064;font-size:12px}}@media print{{body{{background:white}}main{{margin:0 auto}}.record{{box-shadow:none}}}}</style></head><body><main><header><h1>Registros de {escape(ficha['name'])}</h1><div class="meta">{escape(ficha['rpg_name'])} · ID {escape(ficha['id'])}</div><p>Comprovantes de treinos, missões e eventos da ficha.</p></header>{''.join(cards)}<footer>Relatório exportado do MasterFicha. A planilha completa está em registros.csv.</footer></main></body></html>"""
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("provas.html", report)
        archive.writestr("registros.csv", csv_buffer.getvalue().encode("utf-8-sig"))
        archive.writestr("LEIA-ME.txt", "Abra provas.html para visualizar os registros e imagens. O arquivo registros.csv pode ser aberto em uma planilha. As imagens originais estão na pasta imagens/.\n")
        for item in entries:
            archive.writestr(item["file_name"], item["image_bytes"])
    return archive_buffer.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "MasterFicha/1.0"

    def send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > MAX_BODY:
            raise ValueError("O conteúdo enviado está vazio ou excede o limite permitido.")
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("O conteúdo enviado não é um JSON válido.") from exc
        if not isinstance(value, dict):
            raise ValueError("O conteúdo enviado deve ser um objeto.")
        return value

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            with connect_db() as db:
                if path == "/api/rpgs":
                    rows = db.execute("""
                        SELECT r.id, r.name, r.created_at, COUNT(f.id) AS ficha_count
                        FROM rpgs r LEFT JOIN fichas f ON f.rpg_id = r.id
                        GROUP BY r.id ORDER BY r.name COLLATE NOCASE
                    """).fetchall()
                    return self.send_json(200, [dict(r) for r in rows])
                if path == "/api/fichas":
                    query = parse_qs(parsed.query)
                    search = query.get("q", [""])[0].strip()
                    rpg_id = query.get("rpg", [""])[0]
                    clauses, params = [], []
                    if search:
                        clauses.append("(f.name LIKE ? OR f.history LIKE ? OR f.tags LIKE ? OR f.id LIKE ? OR r.name LIKE ?)")
                        pattern = f"%{search}%"
                        params.extend([pattern] * 5)
                    if rpg_id:
                        clauses.append("f.rpg_id = ?")
                        params.append(rpg_id)
                    where = " WHERE " + " AND ".join(clauses) if clauses else ""
                    rows = db.execute("""
                        SELECT f.*, r.name AS rpg_name FROM fichas f JOIN rpgs r ON r.id = f.rpg_id
                    """ + where + " ORDER BY f.updated_at DESC", params).fetchall()
                    return self.send_json(200, [ficha_payload(r) for r in rows])
                if path.startswith("/api/fichas/") and path.endswith("/export"):
                    ficha_id = path[len("/api/fichas/"):-len("/export")].strip("/")
                    archive = build_record_export(db, ficha_id)
                    if archive is None:
                        return self.send_json(404, {"error": "Ficha não encontrada."})
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", 'attachment; filename="masterficha-provas.zip"')
                    self.send_header("Content-Length", str(len(archive)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(archive)
                    return
                if path.startswith("/api/fichas/") and path.endswith("/registros"):
                    ficha_id = path[len("/api/fichas/"):-len("/registros")].strip("/")
                    if not db.execute("SELECT 1 FROM fichas WHERE id = ?", (ficha_id,)).fetchone():
                        return self.send_json(404, {"error": "Ficha não encontrada."})
                    rows = db.execute("SELECT * FROM ficha_registros WHERE ficha_id = ? ORDER BY occurred_on DESC, created_at DESC", (ficha_id,)).fetchall()
                    result = []
                    for row in rows:
                        item = dict(row)
                        item["gains"] = json.loads(item["gains"])
                        result.append(item)
                    return self.send_json(200, result)
                if path.startswith("/api/fichas/"):
                    ficha_id = path.removeprefix("/api/fichas/")
                    row = db.execute("SELECT f.*, r.name AS rpg_name FROM fichas f JOIN rpgs r ON r.id = f.rpg_id WHERE f.id = ?", (ficha_id,)).fetchone()
                    if row is None:
                        return self.send_json(404, {"error": "Ficha não encontrada."})
                    return self.send_json(200, ficha_payload(row))
            return self.serve_static(path)
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except sqlite3.Error:
            self.send_json(500, {"error": "Não foi possível consultar os dados."})

    def do_POST(self) -> None:
        try:
            data = self.read_json()
            with connect_db() as db:
                if self.path.startswith("/api/fichas/") and self.path.endswith("/registros"):
                    ficha_id = self.path[len("/api/fichas/"):-len("/registros")].strip("/")
                    if not db.execute("SELECT 1 FROM fichas WHERE id = ?", (ficha_id,)).fetchone():
                        return self.send_json(404, {"error": "Ficha não encontrada."})
                    record = self.validate_record(data)
                    record_id = str(uuid.uuid4())
                    db.execute("""INSERT INTO ficha_registros
                        (id, ficha_id, kind, occurred_on, description, image_data, gains, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                        (record_id, ficha_id, record["kind"], record["occurred_on"], record["description"],
                         record["image_data"], json.dumps(record["gains"], ensure_ascii=False), now()))
                    return self.send_json(201, {"id": record_id, "ficha_id": ficha_id, **record})
                if self.path == "/api/rpgs":
                    name = clean_text(data.get("name", ""), "nome do RPG", 80, True)
                    rpg_id = str(uuid.uuid4())
                    db.execute("INSERT INTO rpgs(id, name, created_at) VALUES (?, ?, ?)", (rpg_id, name, now()))
                    return self.send_json(201, {"id": rpg_id, "name": name, "ficha_count": 0})
                if self.path == "/api/fichas":
                    ficha = self.validate_ficha(data)
                    if not db.execute("SELECT 1 FROM rpgs WHERE id = ?", (ficha["rpg_id"],)).fetchone():
                        return self.send_json(400, {"error": "Selecione um RPG cadastrado."})
                    ficha_id, timestamp = str(uuid.uuid4()), now()
                    db.execute("""INSERT INTO fichas
                        (id, rpg_id, name, history, attributes, powers, inventory, resource_materials, tags, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (ficha_id, ficha["rpg_id"], ficha["name"], ficha["history"],
                         json.dumps(ficha["attributes"], ensure_ascii=False), json.dumps(ficha["powers"], ensure_ascii=False),
                         json.dumps(ficha["inventory"], ensure_ascii=False), json.dumps(ficha["resource_materials"], ensure_ascii=False),
                         json.dumps(ficha["tags"], ensure_ascii=False), timestamp, timestamp))
                    row = db.execute("SELECT f.*, r.name AS rpg_name FROM fichas f JOIN rpgs r ON r.id=f.rpg_id WHERE f.id=?", (ficha_id,)).fetchone()
                    return self.send_json(201, ficha_payload(row))
            self.send_json(404, {"error": "Rota não encontrada."})
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except sqlite3.IntegrityError as exc:
            message = "Já existe um RPG com esse nome." if "rpgs.name" in str(exc) else "Não foi possível salvar o registro."
            self.send_json(409, {"error": message})
        except sqlite3.Error:
            self.send_json(500, {"error": "Não foi possível salvar os dados."})

    def do_PUT(self) -> None:
        try:
            prefix = "/api/fichas/"
            if not self.path.startswith(prefix):
                return self.send_json(404, {"error": "Rota não encontrada."})
            ficha_id = self.path[len(prefix):]
            ficha = self.validate_ficha(self.read_json())
            with connect_db() as db:
                if not db.execute("SELECT 1 FROM rpgs WHERE id = ?", (ficha["rpg_id"],)).fetchone():
                    return self.send_json(400, {"error": "Selecione um RPG cadastrado."})
                cursor = db.execute("""UPDATE fichas SET rpg_id=?, name=?, history=?, attributes=?, powers=?, inventory=?, resource_materials=?, tags=?, updated_at=? WHERE id=?""",
                    (ficha["rpg_id"], ficha["name"], ficha["history"], json.dumps(ficha["attributes"], ensure_ascii=False),
                     json.dumps(ficha["powers"], ensure_ascii=False), json.dumps(ficha["inventory"], ensure_ascii=False),
                     json.dumps(ficha["resource_materials"], ensure_ascii=False), json.dumps(ficha["tags"], ensure_ascii=False), now(), ficha_id))
                if cursor.rowcount == 0:
                    return self.send_json(404, {"error": "Ficha não encontrada."})
                row = db.execute("SELECT f.*, r.name AS rpg_name FROM fichas f JOIN rpgs r ON r.id=f.rpg_id WHERE f.id=?", (ficha_id,)).fetchone()
                self.send_json(200, ficha_payload(row))
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
        except sqlite3.Error:
            self.send_json(500, {"error": "Não foi possível atualizar a ficha."})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        try:
            with connect_db() as db:
                if path.startswith("/api/registros/"):
                    record_id = path.removeprefix("/api/registros/")
                    cursor = db.execute("DELETE FROM ficha_registros WHERE id = ?", (record_id,))
                    if cursor.rowcount == 0:
                        return self.send_json(404, {"error": "Registro não encontrado."})
                    return self.send_json(200, {"ok": True})
                if path.startswith("/api/fichas/"):
                    ficha_id = path.removeprefix("/api/fichas/")
                    cursor = db.execute("DELETE FROM fichas WHERE id = ?", (ficha_id,))
                    if cursor.rowcount == 0:
                        return self.send_json(404, {"error": "Ficha não encontrada."})
                    return self.send_json(200, {"ok": True})
                if path.startswith("/api/rpgs/"):
                    rpg_id = path.removeprefix("/api/rpgs/")
                    cursor = db.execute("DELETE FROM rpgs WHERE id = ?", (rpg_id,))
                    if cursor.rowcount == 0:
                        return self.send_json(404, {"error": "RPG não encontrado."})
                    return self.send_json(200, {"ok": True})
            self.send_json(404, {"error": "Rota não encontrada."})
        except sqlite3.IntegrityError:
            self.send_json(409, {"error": "Este RPG possui fichas. Remova ou mova as fichas antes de excluir o RPG."})
        except sqlite3.Error:
            self.send_json(500, {"error": "Não foi possível excluir o registro."})

    @staticmethod
    def validate_ficha(data: dict) -> dict:
        rpg_id = clean_text(data.get("rpg_id", ""), "RPG", 36, True)
        attributes = clean_rows(data.get("attributes", []), "attributes")
        validate_attribute_formulas(attributes)
        powers = clean_rows(data.get("powers", []), "powers")
        attribute_names = {attribute["name"].casefold() for attribute in attributes}
        for power in powers:
            for effect in power["effects"]:
                if effect["attribute"].casefold() not in attribute_names:
                    raise ValueError(f'O poder "{power["name"]}" usa o atributo "{effect["attribute"]}", que não está cadastrado na ficha.')
        return {
            "rpg_id": rpg_id,
            "name": clean_text(data.get("name", ""), "nome da ficha", 120, True),
            "history": clean_text(data.get("history", ""), "história", 10000),
            "attributes": attributes,
            "powers": powers,
            "inventory": clean_rows(data.get("inventory", []), "inventory"),
            "resource_materials": clean_resource_materials(data.get("resource_materials", {"fields": [], "rows": []})),
            "tags": clean_tags(data.get("tags", [])),
        }

    @staticmethod
    def validate_record(data: dict) -> dict:
        kind = data.get("kind")
        if kind not in ("treino", "missao", "evento"):
            raise ValueError("Escolha Treino, Missão ou Evento.")
        occurred_on = clean_text(data.get("occurred_on", ""), "data", 10, True)
        try:
            datetime.strptime(occurred_on, "%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("Informe uma data válida.") from exc
        image_data = data.get("image_data")
        if not isinstance(image_data, str) or len(image_data) > 2_800_000:
            raise ValueError("Adicione uma imagem PNG, JPEG ou WebP de até 2 MB.")
        match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})", image_data)
        if not match:
            raise ValueError("A imagem precisa ser PNG, JPEG ou WebP.")
        try:
            image_bytes = base64.b64decode(match.group(2), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Não foi possível ler a imagem enviada.") from exc
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("A imagem deve ter no máximo 2 MB.")
        mime = match.group(1)
        signatures = {"png": b"\x89PNG\r\n\x1a\n", "jpeg": b"\xff\xd8\xff", "webp": b"RIFF"}
        if not image_bytes.startswith(signatures[mime]) or (mime == "webp" and image_bytes[8:12] != b"WEBP"):
            raise ValueError("O conteúdo do arquivo não corresponde ao formato da imagem.")
        gains = data.get("gains", [])
        if not isinstance(gains, list) or len(gains) > 20:
            raise ValueError("Informe até 20 ganhos de atributo por registro.")
        clean_gains = []
        for gain in gains:
            if not isinstance(gain, dict):
                raise ValueError("Há um ganho de atributo inválido.")
            attribute = clean_text(gain.get("attribute", ""), "atributo recebido", 80, True)
            amount = gain.get("amount")
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0 or amount > 1_000_000 or not math.isfinite(amount):
                raise ValueError("O valor de cada ganho deve ser maior que zero.")
            clean_gains.append({"attribute": attribute, "amount": amount})
        return {
            "kind": kind,
            "occurred_on": occurred_on,
            "description": clean_text(data.get("description", ""), "descrição", 3000, True),
            "image_data": image_data,
            "gains": clean_gains,
        }

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.lstrip("/")
        file_path = (ROOT / relative).resolve()
        if ROOT not in file_path.parents or not file_path.is_file():
            return self.send_json(404, {"error": "Página não encontrada."})
        content_type = "text/html; charset=utf-8" if file_path.suffix == ".html" else "text/css; charset=utf-8" if file_path.suffix == ".css" else "text/javascript; charset=utf-8"
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        if os.environ.get("MASTERFICHA_ACCESS_LOG") == "1":
            super().log_message(format, *args)


if __name__ == "__main__":
    initialize_db()
    port = int(os.environ.get("PORT", "8000"))
    print(f"MasterFicha disponível em http://127.0.0.1:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
